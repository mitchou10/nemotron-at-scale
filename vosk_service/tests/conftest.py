"""Fixtures: a scripted fake engine, so tests need no Vosk model."""

import struct
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

VOCAB = ["bonjour", "tout", "le", "monde", "ceci", "est", "un", "test"]
END = b"\xff\xff"  # a chunk starting with 0xff closes the utterance in the fake recognizer


class FakeRecognizer:
    """Adds one word of VOCAB per audio chunk; a chunk starting with 0xff ends the utterance."""

    def __init__(self, rate: int, words: bool) -> None:
        self.rate = rate
        self.words = words
        self.calls: list[bytes] = []
        self._current: list[tuple[str, float, float]] = []
        self._counter = 0
        self._time = 0.0
        self._result: dict[str, Any] = {"text": ""}

    def accept_waveform(self, data: bytes) -> bool:
        self.calls.append(data)
        if data[:1] == b"\xff":
            self._result = self._flush()
            return True
        word = VOCAB[self._counter % len(VOCAB)]
        self._counter += 1
        self._current.append((word, self._time, self._time + 0.3))
        self._time += 0.3
        return False

    def partial_result(self) -> dict[str, Any]:
        return {"partial": " ".join(word for word, _, _ in self._current)}

    def result(self) -> dict[str, Any]:
        return self._result

    def final_result(self) -> dict[str, Any]:
        return self._flush()

    def _flush(self) -> dict[str, Any]:
        if not self._current:
            return {"text": ""}
        result = {
            "text": " ".join(word for word, _, _ in self._current),
            "result": [{"word": w, "start": s, "end": e, "conf": 0.9} for w, s, e in self._current],
        }
        self._current = []
        return result


class FakeEngine:
    def __init__(self, name: str = "vosk-model-small-fr-0.22", language: str = "fr") -> None:
        self.name = name
        self.language = language
        self.created: list[FakeRecognizer] = []

    def create_recognizer(self, sample_rate: int, words: bool) -> FakeRecognizer:
        recognizer = FakeRecognizer(sample_rate, words)
        self.created.append(recognizer)
        return recognizer


def wav_bytes(
    samples: bytes,
    *,
    rate: int = 16_000,
    channels: int = 1,
    bits: int = 16,
    tag: int = 1,
    extensible: bool = False,
) -> bytes:
    """A minimal WAV file around raw sample bytes."""
    block = channels * bits // 8
    fmt = struct.pack(
        "<HHIIHH", 0xFFFE if extensible else tag, channels, rate, rate * block, block, bits
    )
    if extensible:
        fmt += struct.pack("<HHIH", 22, bits, 0, tag) + b"\x00" * 14
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += (
        b"data" + struct.pack("<I", len(samples)) + samples + (b"\x00" if len(samples) & 1 else b"")
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None, model_dir="/nonexistent", max_streams=2, threads=2, api_key=None
    )


@pytest.fixture
def client(settings: Settings, engine: FakeEngine) -> Iterator[TestClient]:
    with TestClient(create_app(settings, engine)) as test_client:
        yield test_client

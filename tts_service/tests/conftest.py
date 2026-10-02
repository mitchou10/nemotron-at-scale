"""Fixtures: a fake engine, so tests need no Piper voice."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.engine import AudioChunk, VoiceInfo
from app.main import create_app

RATE = 22050


class FakeEngine:
    """One chunk per sentence, 0.1 s of a constant tone each; remembers what it was asked."""

    name = "fake"

    def __init__(self) -> None:
        self.voices = [
            VoiceInfo("fr_FR-test-medium", "fr", RATE),
            VoiceInfo("en_US-test-low", "en", RATE),
        ]
        self.calls: list[tuple[str, str, float]] = []

    def synthesize(self, text: str, voice: str, speed: float) -> Iterator[AudioChunk]:
        self.calls.append((text, voice, speed))
        for _ in (s for s in text.replace("!", ".").split(".") if s.strip()):
            yield AudioChunk(b"\x10\x20" * (RATE // 10), RATE)


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def make_client(engine: FakeEngine):  # type: ignore[no-untyped-def]
    def build(**settings: object) -> TestClient:
        app = create_app(Settings(**settings), engine=engine, load_model=False)  # type: ignore[arg-type]
        return TestClient(app)

    return build


@pytest.fixture
def client(make_client) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    with make_client() as test_client:
        yield test_client

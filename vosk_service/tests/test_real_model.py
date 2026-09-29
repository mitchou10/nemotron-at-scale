"""Optional test with a real Vosk model.

Run: VOSK_TEST_MODEL_DIR=./models pytest tests/test_real_model.py

Set VOSK_TEST_MODEL_NAME to pick the model (default: the first vosk-model-* folder found).
"""

import os
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import wav_bytes

MODEL_DIR = os.environ.get("VOSK_TEST_MODEL_DIR")

pytestmark = pytest.mark.skipif(not MODEL_DIR, reason="set VOSK_TEST_MODEL_DIR to run")


@pytest.fixture(scope="module")
def real_client() -> TestClient:
    from app.vosk_engine import VoskEngine

    root = Path(MODEL_DIR or ".")
    name = (
        os.environ.get("VOSK_TEST_MODEL_NAME")
        or sorted(p.name for p in root.glob("vosk-model-*"))[0]
    )
    settings = Settings(_env_file=None, model_dir=str(root), model_name=name, max_streams=2)
    with TestClient(create_app(settings, VoskEngine.load(settings))) as client:
        yield client


def test_real_model_is_ready(real_client: TestClient) -> None:
    ready = real_client.get("/ready").json()
    assert ready["ready"] is True
    assert ready["model"].startswith("vosk-model")


def test_silence_gives_an_empty_transcript(real_client: TestClient) -> None:
    silence = struct.pack("<h", 0) * 16_000
    response = real_client.post(
        "/v1/audio/transcriptions", files={"file": ("s.wav", wav_bytes(silence))}
    )
    assert response.status_code == 200
    assert response.json() == {"text": ""}


def test_real_realtime_stream_completes(real_client: TestClient) -> None:
    with real_client.websocket_connect("/v1/audio/transcriptions/realtime") as ws:
        assert ws.receive_json()["type"] == "session.created"
        for _ in range(10):
            ws.send_bytes(struct.pack("<h", 0) * 1600)
        ws.send_json({"type": "input_audio_buffer.commit"})
        assert ws.receive_json()["type"] == "input_audio_buffer.committed"


def test_sample_audio_is_transcribed(real_client: TestClient) -> None:
    sample = os.environ.get("VOSK_TEST_AUDIO")
    if not sample:
        pytest.skip("set VOSK_TEST_AUDIO to a 16 kHz mono WAV to check a real transcription")
    with open(sample, "rb") as audio:
        response = real_client.post("/v1/audio/transcriptions", files={"file": ("a.wav", audio)})
    assert response.json()["text"]

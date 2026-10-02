"""Real Piper voice: skipped unless TTS_TEST_VOICE_DIR holds fr_FR-siwis-medium."""

import io
import os
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

VOICE_DIR = os.environ.get("TTS_TEST_VOICE_DIR", "")

pytestmark = pytest.mark.skipif(
    not (Path(VOICE_DIR) / "fr_FR-siwis-medium.onnx").is_file(),
    reason="set TTS_TEST_VOICE_DIR to a folder with fr_FR-siwis-medium.onnx(.json)",
)


def test_real_synthesis() -> None:
    app = create_app(Settings(voice_dir=VOICE_DIR, voices=["fr_FR-siwis-medium"]))
    with TestClient(app) as client:
        for _ in range(100):  # the voice loads in the background
            if client.get("/ready").status_code == 200:
                break
            import time

            time.sleep(0.2)
        response = client.post(
            "/v1/audio/speech",
            json={"input": "Bonjour tout le monde.", "voice": "alloy", "response_format": "wav"},
        )
        assert response.status_code == 200
        with wave.open(io.BytesIO(response.content)) as wav:
            assert wav.getframerate() == 22050
            assert wav.getnframes() > 22050 // 2  # at least half a second of speech

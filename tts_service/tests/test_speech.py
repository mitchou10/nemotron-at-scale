"""POST /v1/audio/speech."""

import io
import struct
import wave

import pytest
from fastapi.testclient import TestClient

from tests.conftest import RATE, FakeEngine


def speak(client: TestClient, **body: object):  # type: ignore[no-untyped-def]
    payload = {"model": "tts-1", "input": "Bonjour. Au revoir.", "voice": "alloy", **body}
    return client.post("/v1/audio/speech", json=payload)


def test_default_format_is_mp3(client: TestClient) -> None:
    response = speak(client)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert len(response.content) > 100
    # an MP3 frame header starts with 11 bits of sync
    assert response.content[0] == 0xFF
    assert response.content[1] & 0xE0 == 0xE0


def test_wav_has_a_correct_header(client: TestClient) -> None:
    response = speak(client, response_format="wav")
    assert response.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(response.content)) as wav:
        assert wav.getframerate() == RATE
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 2 * RATE // 10  # two sentences
    assert response.headers["content-length"] == str(len(response.content))


def test_pcm_is_the_raw_audio(client: TestClient) -> None:
    response = speak(client, response_format="pcm")
    assert response.headers["content-type"] == "audio/pcm"
    assert len(response.content) == 2 * (RATE // 10) * 2
    assert struct.unpack("<h", response.content[:2])[0] == 0x2010


def test_flac(client: TestClient) -> None:
    response = speak(client, response_format="flac")
    assert response.content[:4] == b"fLaC"


@pytest.mark.parametrize("fmt", ["opus", "aac", "ogg"])
def test_unsupported_formats_are_refused_with_the_list(client: TestClient, fmt: str) -> None:
    response = speak(client, response_format=fmt)
    assert response.status_code == 400
    assert "mp3" in response.json()["error"]["message"]


def test_exact_voice_name(client: TestClient, engine: FakeEngine) -> None:
    response = speak(client, voice="en_US-test-low", response_format="pcm")
    assert response.headers["x-voice"] == "en_US-test-low"
    assert engine.calls[-1][1] == "en_US-test-low"


def test_openai_voice_names_are_spread_over_the_installed_voices(client: TestClient) -> None:
    first = speak(client, voice="alloy", response_format="pcm").headers["x-voice"]
    second = speak(client, voice="ash", response_format="pcm").headers["x-voice"]
    assert {first, second} == {"fr_FR-test-medium", "en_US-test-low"}


def test_unknown_voice(client: TestClient) -> None:
    response = speak(client, voice="nobody")
    assert response.status_code == 400
    assert "fr_FR-test-medium" in response.json()["error"]["message"]


def test_speed_is_passed_to_the_engine(client: TestClient, engine: FakeEngine) -> None:
    speak(client, speed=1.5, response_format="pcm")
    assert engine.calls[-1][2] == 1.5


@pytest.mark.parametrize("speed", [0.1, 5])
def test_speed_out_of_range(client: TestClient, speed: float) -> None:
    assert speak(client, speed=speed).status_code == 400


def test_input_is_required_and_bounded(make_client) -> None:  # type: ignore[no-untyped-def]
    with make_client(max_input_chars=10) as client:
        assert speak(client, input="   ").status_code == 400
        assert speak(client, input="x" * 11).status_code == 400
        assert client.post("/v1/audio/speech", json={"voice": "alloy"}).status_code == 400
        assert speak(client, input="Court.", response_format="pcm").status_code == 200


def test_input_with_nothing_to_say(client: TestClient) -> None:
    response = speak(client, input="...")
    assert response.status_code == 400
    assert "nothing to say" in response.json()["error"]["message"]


def test_unknown_fields_are_ignored(client: TestClient) -> None:
    response = speak(client, instructions="Parle doucement", stream_format="audio")
    assert response.status_code == 200


def test_errors_use_the_openai_shape(client: TestClient) -> None:
    body = speak(client, input="").json()
    assert set(body["error"]) == {"message", "type"}


def test_a_failing_engine_gives_a_500_and_frees_the_slot(make_client, engine: FakeEngine) -> None:  # type: ignore[no-untyped-def]
    def broken(*_: object):  # type: ignore[no-untyped-def]
        raise RuntimeError("onnx exploded")
        yield

    engine.synthesize = broken  # type: ignore[method-assign]
    with make_client(max_requests=1) as client:
        response = speak(client)
        assert response.status_code == 500
        assert "onnx exploded" in response.json()["error"]["message"]
        assert client.app.state.server.active_requests == 0


def test_requests_beyond_the_limit_get_429(make_client) -> None:  # type: ignore[no-untyped-def]
    with make_client(max_requests=1) as client:
        assert client.app.state.server.try_open_request()  # a synthesis is already running
        response = speak(client)
        assert response.status_code == 429
        assert response.json()["error"]["type"] == "rate_limit_error"


def test_the_slot_is_released_after_a_response(client: TestClient) -> None:
    speak(client, response_format="pcm")
    assert client.app.state.server.active_requests == 0


def test_api_key(make_client) -> None:  # type: ignore[no-untyped-def]
    with make_client(api_key="secret") as client:
        assert speak(client).status_code == 401
        ok = client.post(
            "/v1/audio/speech",
            json={"input": "Salut.", "voice": "alloy", "response_format": "pcm"},
            headers={"Authorization": "Bearer secret"},
        )
        assert ok.status_code == 200

"""Service routes, metrics and start-up."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_ready_lists_the_voices(client: TestClient) -> None:
    body = client.get("/ready").json()
    assert body["ready"] is True
    assert body["capabilities"] == ["tts"]
    assert body["voices"] == ["fr_FR-test-medium", "en_US-test-low"]


def test_health_live_version(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/live").json() == {"status": "alive"}
    assert "version" in client.get("/version").json()


def test_models_are_in_the_openai_format(client: TestClient) -> None:
    body = client.get("/v1/models").json()
    assert body["object"] == "list"
    assert {m["id"] for m in body["data"]} == {"tts-1", "tts-1-hd"}


def test_voices_route(client: TestClient) -> None:
    data = client.get("/v1/audio/voices").json()["data"]
    assert data[0] == {"id": "fr_FR-test-medium", "language": "fr", "sample_rate": 22050}


def test_not_ready_while_loading() -> None:
    app = create_app(Settings(), engine=None, load_model=False)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 503
        assert client.get("/ready").status_code == 503
        assert client.get("/live").status_code == 200
        assert client.get("/v1/models").status_code == 503
        response = client.post("/v1/audio/speech", json={"input": "Salut", "voice": "alloy"})
        assert response.status_code == 503
        assert "not loaded" in response.json()["error"]["message"]


def test_ready_capacity(make_client) -> None:  # type: ignore[no-untyped-def]
    with make_client(max_requests=1) as client:
        assert client.get("/ready/capacity").status_code == 200
        client.app.state.server.try_open_request()
        assert client.get("/ready/capacity").status_code == 503


def test_metrics_count_requests_and_audio(client: TestClient) -> None:
    client.post(
        "/v1/audio/speech",
        json={"input": "Un. Deux.", "voice": "alloy", "response_format": "pcm"},
    )
    text = client.get("/metrics").text
    assert 'tts_speech_requests_total{status="ok"} 1.0' in text
    assert "tts_input_characters_total 9.0" in text
    assert "tts_audio_seconds_total" in text


def test_playground(client: TestClient) -> None:
    assert "Synthèse vocale" in client.get("/").text


def test_settings_parse_voices_from_a_comma_list(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("TTS_VOICES", "fr_FR-siwis-medium, en_US-lessac-low")
    assert Settings().voices == ["fr_FR-siwis-medium", "en_US-lessac-low"]
    monkeypatch.setenv("TTS_VOICES", '["a-b-c"]')
    assert Settings().voices == ["a-b-c"]

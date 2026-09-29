"""HTTP route tests."""

from fastapi.testclient import TestClient

from app import __version__
from app.config import Settings
from app.main import create_app
from tests.conftest import FakeEngine, wav_bytes

SAMPLES = b"\x01\x00" * 16_000  # 1 s at 16 kHz: four 0.25 s chunks, one word each


def upload(client: TestClient, wav: bytes, **fields: str):
    return client.post(
        "/v1/audio/transcriptions", files={"file": ("a.wav", wav)}, data=fields or None
    )


def test_service_routes(client: TestClient) -> None:
    assert client.get("/version").json() == {"version": __version__}
    assert client.get("/health").json() == {"status": "ok", "version": __version__}
    ready = client.get("/ready").json()
    assert ready["ready"] is True
    assert (ready["model"], ready["language"], ready["max_streams"]) == (
        "vosk-model-small-fr-0.22",
        "fr",
        2,
    )
    assert ready["active_streams"] == 0
    assert client.get("/v1/models").json() == {
        "object": "list",
        "data": [
            {
                "id": "vosk-model-small-fr-0.22",
                "object": "model",
                "owned_by": "vosk",
                "capabilities": ["asr"],
                "language": "fr",
            }
        ],
    }


def test_not_ready_until_the_model_is_loaded(settings: Settings) -> None:
    with TestClient(create_app(settings, engine=None, load_model=False)) as client:
        client.app.state.server.engine = None
        client.app.state.server.load_error = "boom"
        assert client.get("/health").status_code == 503
        ready = client.get("/ready")
        assert (ready.status_code, ready.json()) == (503, {"ready": False, "detail": "boom"})
        models = client.get("/v1/models")
        assert models.status_code == 503
        assert models.json()["error"]["type"] == "server_error"
        response = upload(client, wav_bytes(SAMPLES))
        assert response.status_code == 503
        assert "not loaded: boom" in response.json()["error"]["message"]


def test_loading_message_before_any_error(settings: Settings) -> None:
    with TestClient(create_app(settings, engine=None, load_model=False)) as client:
        client.app.state.server.engine = None
        assert client.get("/ready").json()["detail"] == "the model is loading"
        assert "not loaded" in upload(client, wav_bytes(SAMPLES)).json()["error"]["message"]


def test_json_transcription(client: TestClient) -> None:
    response = upload(client, wav_bytes(SAMPLES))
    assert response.status_code == 200
    assert response.json() == {"text": "bonjour tout le monde"}


def test_verbose_json_transcription(client: TestClient) -> None:
    body = upload(client, wav_bytes(SAMPLES), response_format="verbose_json").json()
    assert (body["task"], body["language"], body["duration"]) == ("transcribe", "fr", 1.0)
    assert body["text"] == "bonjour tout le monde"
    assert [w["word"] for w in body["words"]] == ["bonjour", "tout", "le", "monde"]
    assert (
        upload(client, wav_bytes(SAMPLES), response_format="verbose_json", language="en").json()[
            "language"
        ]
        == "en"
    )


def test_text_srt_and_vtt_formats(client: TestClient) -> None:
    text = upload(client, wav_bytes(SAMPLES), response_format="text")
    assert (text.text, text.headers["content-type"].split(";")[0]) == (
        "bonjour tout le monde",
        "text/plain",
    )
    srt = upload(client, wav_bytes(SAMPLES), response_format="srt")
    assert srt.headers["content-type"].startswith("application/x-subrip")
    assert srt.text.startswith("1\n00:00:00,000 --> 00:00:01,200\nbonjour tout le monde")
    vtt = upload(client, wav_bytes(SAMPLES), response_format="vtt")
    assert vtt.headers["content-type"].startswith("text/vtt")
    assert vtt.text.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.200")


def test_unknown_format_is_rejected(client: TestClient) -> None:
    response = upload(client, wav_bytes(SAMPLES), response_format="xml")
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert "response_format" in response.json()["error"]["message"]


def test_invalid_audio_is_rejected(client: TestClient) -> None:
    response = upload(client, b"definitely not a wav")
    assert response.status_code == 400
    assert "RIFF/WAVE" in response.json()["error"]["message"]


def test_missing_file_is_a_400_with_the_api_error_shape(client: TestClient) -> None:
    response = client.post("/v1/audio/transcriptions", data={"model": "x"})
    assert response.status_code == 400
    assert set(response.json()["error"]) == {"message", "type"}


def test_oversized_upload_is_rejected(engine: FakeEngine) -> None:
    settings = Settings(_env_file=None, max_upload_mb=1)
    with TestClient(create_app(settings, engine)) as client:
        big = wav_bytes(b"\x00\x00" * 700_000)
        response = upload(client, big)
        assert response.status_code == 413
        assert "1 MB" in response.json()["error"]["message"]


def test_transcription_metrics(client: TestClient) -> None:
    upload(client, wav_bytes(SAMPLES))
    upload(client, b"bad")
    text = client.get("/metrics").text
    assert 'vosk_transcription_requests_total{status="ok"} 1.0' in text
    assert 'vosk_transcription_requests_total{status="error"} 1.0' in text
    assert "vosk_audio_seconds_total 1.0" in text
    assert "vosk_max_streams 2.0" in text


def test_api_key_protects_v1_routes_only(engine: FakeEngine) -> None:
    settings = Settings(_env_file=None, api_key="secret")
    with TestClient(create_app(settings, engine)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.get("/metrics").status_code == 200
        for path in ("/v1/models",):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["error"]["message"] == "invalid or missing bearer token"
        assert client.get("/v1/models", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert client.get("/v1/models", headers={"Authorization": "Basic x"}).status_code == 401
        good = {"Authorization": "Bearer secret"}
        assert client.get("/v1/models", headers=good).status_code == 200
        assert (
            client.post(
                "/v1/audio/transcriptions", files={"file": ("a.wav", wav_bytes(SAMPLES))}
            ).status_code
            == 401
        )
        ok = client.post(
            "/v1/audio/transcriptions", files={"file": ("a.wav", wav_bytes(SAMPLES))}, headers=good
        )
        assert ok.status_code == 200


def test_cors_origin_is_allowed_when_configured(engine: FakeEngine) -> None:
    settings = Settings(_env_file=None, cors_origin="http://localhost:3000")
    with TestClient(create_app(settings, engine)) as client:
        response = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_files_are_decoded_utterance_by_utterance(client: TestClient) -> None:
    quarter = b"\x01\x00" * 4000  # 0.25 s: one word in the fake recognizer
    ending = b"\xff\xff" + b"\x00\x00" * 3999  # a chunk that closes the utterance
    wav = wav_bytes(quarter + ending + quarter)
    assert upload(client, wav).json() == {"text": "bonjour tout"}


def test_playground_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "vosk_service" in response.text
    assert "/v1/audio/transcriptions/realtime" in response.text


def test_realtime_route_is_documented_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/v1/audio/transcriptions/realtime"]["get"]
    assert operation["summary"] == "Live transcription (WebSocket)"
    assert "input_audio_buffer.commit" in operation["description"]
    assert "conversation.item.input_audio_transcription.delta" in operation["description"]
    assert "/v1/audio/transcriptions" in schema["paths"]


def test_plain_http_on_the_realtime_route_says_to_use_a_websocket(client: TestClient) -> None:
    response = client.get("/v1/audio/transcriptions/realtime")
    assert response.status_code == 426
    assert response.headers["upgrade"] == "websocket"
    assert "WebSocket endpoint" in response.json()["error"]["message"]


def test_concurrent_requests_are_capped_with_429(engine: FakeEngine) -> None:
    settings = Settings(_env_file=None, max_requests=1)
    with TestClient(create_app(settings, engine)) as client:
        server = client.app.state.server
        assert server.try_open_request()  # another transcription is running
        response = upload(client, wav_bytes(SAMPLES))
        assert response.status_code == 429
        assert response.json()["error"]["message"] == "too many concurrent transcription requests"
        server.close_request()
        assert upload(client, wav_bytes(SAMPLES)).status_code == 200
        assert (
            'vosk_transcription_requests_total{status="rejected"} 1.0'
            in client.get("/metrics").text
        )


def test_the_request_slot_is_released_after_an_error(engine: FakeEngine) -> None:
    settings = Settings(_env_file=None, max_requests=1)
    with TestClient(create_app(settings, engine)) as client:
        assert upload(client, b"bad").status_code == 400
        assert upload(client, wav_bytes(SAMPLES)).status_code == 200
        assert client.app.state.server.active_requests == 0


def test_liveness_answers_even_without_a_model(settings: Settings) -> None:
    with TestClient(create_app(settings, engine=None, load_model=False)) as client:
        assert client.get("/live").json() == {"status": "alive"}
        assert client.get("/health").status_code == 503


def test_capacity_readiness_follows_the_model_and_the_load(
    settings: Settings, engine: FakeEngine
) -> None:
    with TestClient(create_app(settings, engine=None, load_model=False)) as client:
        loading = client.get("/ready/capacity")
        assert (loading.status_code, loading.json()["detail"]) == (503, "the model is loading")

        server = client.app.state.server
        server.engine = engine
        ok = client.get("/ready/capacity")
        assert (ok.status_code, ok.json()) == (
            200,
            {"ready": True, "active_streams": 0, "max_streams": 2},
        )

        server.active_streams = 2  # full: the instance leaves the load balancer
        full = client.get("/ready/capacity")
        assert (full.status_code, full.json()["detail"]) == (503, "at capacity")
        assert client.get("/ready").status_code == 200  # still ready for direct connections

        server.load_error = "boom"
        server.engine = None
        assert client.get("/ready/capacity").json()["detail"] == "boom"

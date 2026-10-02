"""Text-to-speech relay."""

import httpx
import pytest
from httpx import AsyncClient

from app.config import settings
from app.main import app, build_tts_client


def mock_service(handler):  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://tts")


@pytest.fixture(autouse=True)
def reset_tts():  # type: ignore[no-untyped-def]
    yield
    app.state.tts = None


async def test_disabled_by_default(client: AsyncClient) -> None:
    app.state.tts = None
    response = await client.post("/api/v1/audio/speech", json={"input": "a", "voice": "alloy"})
    assert response.status_code == 503
    assert response.json()["error"]["type"] == "server_error"


async def test_speech_is_relayed_with_status_body_and_voice(client: AsyncClient) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(
            path=request.url.path, body=request.content, type=request.headers["content-type"]
        )
        return httpx.Response(
            200, content=b"ID3-audio", headers={"content-type": "audio/mpeg", "x-voice": "fr_FR-x"}
        )

    app.state.tts = mock_service(handler)
    payload = {"model": "tts-1", "input": "Bonjour", "voice": "alloy"}
    response = await client.post("/api/v1/audio/speech", json=payload)

    assert response.status_code == 200
    assert response.content == b"ID3-audio"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["x-voice"] == "fr_FR-x"
    assert seen["path"] == "/v1/audio/speech"
    assert b"Bonjour" in seen["body"]  # type: ignore[operator]
    assert seen["type"] == "application/json"


async def test_service_errors_are_passed_through(client: AsyncClient) -> None:
    error = {"error": {"message": "unknown voice 'x'", "type": "invalid_request_error"}}
    app.state.tts = mock_service(lambda request: httpx.Response(400, json=error))
    response = await client.post("/api/v1/audio/speech", json={"input": "a", "voice": "x"})
    assert response.status_code == 400
    assert response.json() == error


async def test_unreachable_service_gives_502(client: AsyncClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    app.state.tts = mock_service(handler)
    response = await client.post("/api/v1/audio/speech", json={"input": "a", "voice": "alloy"})
    assert response.status_code == 502
    assert "unreachable" in response.json()["error"]["message"]


async def test_voices_route(client: AsyncClient) -> None:
    body = {"object": "list", "data": [{"id": "fr_FR-x"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/audio/voices"
        return httpx.Response(200, json=body)

    app.state.tts = mock_service(handler)
    response = await client.get("/api/v1/audio/voices")
    assert response.json() == body


def test_client_follows_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TTS_ENABLED", False)
    assert build_tts_client() is None
    monkeypatch.setattr(settings, "TTS_ENABLED", True)
    monkeypatch.setattr(settings, "TTS_URL", "http://voice:9000")
    monkeypatch.setattr(settings, "TTS_API_KEY", "secret")
    client = build_tts_client()
    assert client is not None
    assert str(client.base_url) == "http://voice:9000"
    assert client.headers["authorization"] == "Bearer secret"

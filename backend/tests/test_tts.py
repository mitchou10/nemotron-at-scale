"""Text-to-speech gateway: routing to the registered instances."""

from collections.abc import Callable

import httpx
import pytest
from httpx import AsyncClient

from app.main import app
from app.services.registry import InMemoryRegistryStore, RegisteredInstance
from app.services.tts_pool import TtsPool

SPEECH = {"model": "tts-1", "input": "Bonjour", "voice": "alloy"}


async def make_pool(
    registry: InMemoryRegistryStore,
    handler: Callable[[httpx.Request], httpx.Response],
    *ids: str,
    api_key: str | None = None,
) -> TtsPool:
    for instance_id in ids:
        await registry.upsert(RegisteredInstance(instance_id, "tts", f"http://{instance_id}", 4))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    pool = TtsPool(registry, 30, api_key=api_key, client=client)
    app.state.tts_pool = pool
    return pool


def audio(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        content=f"audio from {request.url.host}".encode(),
        headers={"content-type": "audio/mpeg", "x-voice": "fr_FR-x"},
    )


async def test_no_instance_registered(client: AsyncClient) -> None:
    app.state.tts_pool = None
    response = await client.post("/api/v1/audio/speech", json=SPEECH)
    assert response.status_code == 503
    assert response.json()["error"]["type"] == "server_error"


async def test_nothing_registered_says_so(
    client: AsyncClient, registry: InMemoryRegistryStore
) -> None:
    await make_pool(registry, audio)
    response = await client.post("/api/v1/audio/speech", json=SPEECH)
    assert response.status_code == 503
    assert "no text-to-speech instance is registered" in response.json()["error"]["message"]


async def test_speech_is_relayed_with_status_body_and_voice(
    client: AsyncClient, registry: InMemoryRegistryStore
) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(
            url=str(request.url),
            body=request.content,
            type=request.headers["content-type"],
            auth=request.headers.get("authorization"),
        )
        return audio(request)

    await make_pool(registry, handler, "tts-a", api_key="k")
    response = await client.post("/api/v1/audio/speech", json=SPEECH)

    assert response.status_code == 200
    assert response.content == b"audio from tts-a"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["x-voice"] == "fr_FR-x"
    assert seen["url"] == "http://tts-a/v1/audio/speech"
    assert b"Bonjour" in seen["body"]  # type: ignore[operator]
    assert seen["type"] == "application/json"
    assert seen["auth"] == "Bearer k"


async def test_the_least_loaded_instance_gets_the_request(
    client: AsyncClient, registry: InMemoryRegistryStore
) -> None:
    pool = await make_pool(registry, audio, "tts-a", "tts-b")
    pool._in_flight["tts-a"] = 3  # tts-a is busy
    response = await client.post("/api/v1/audio/speech", json=SPEECH)
    assert response.content == b"audio from tts-b"


async def test_load_is_released_once_the_response_is_sent(
    client: AsyncClient, registry: InMemoryRegistryStore
) -> None:
    pool = await make_pool(registry, audio, "tts-a")
    await client.post("/api/v1/audio/speech", json=SPEECH)
    assert pool.load() == {"tts-a": 0}


async def test_unreachable_instance_is_skipped_then_left_out(
    client: AsyncClient, registry: InMemoryRegistryStore
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "tts-a":
            raise httpx.ConnectError("refused")
        return audio(request)

    pool = await make_pool(registry, handler, "tts-a", "tts-b")
    response = await client.post("/api/v1/audio/speech", json=SPEECH)
    assert response.content == b"audio from tts-b"
    assert [i.id for i in await pool.instances()] == ["tts-b", "tts-a"]  # tts-a cools down last


async def test_full_instance_is_skipped(
    client: AsyncClient, registry: InMemoryRegistryStore
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "tts-a":
            return httpx.Response(429, json={"error": {"message": "full"}})
        return audio(request)

    await make_pool(registry, handler, "tts-a", "tts-b")
    assert (await client.post("/api/v1/audio/speech", json=SPEECH)).content == b"audio from tts-b"


async def test_when_every_instance_is_full_the_client_gets_the_429(
    client: AsyncClient, registry: InMemoryRegistryStore
) -> None:
    full = httpx.Response(429, json={"error": {"message": "full", "type": "rate_limit_error"}})
    pool = await make_pool(registry, lambda request: full, "tts-a", "tts-b")
    response = await client.post("/api/v1/audio/speech", json=SPEECH)
    assert response.status_code == 429
    assert response.json()["error"]["type"] == "rate_limit_error"
    assert pool.load() == {"tts-a": 0, "tts-b": 0}


async def test_a_bad_request_is_not_retried(
    client: AsyncClient, registry: InMemoryRegistryStore
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(400, json={"error": {"message": "unknown voice"}})

    await make_pool(registry, handler, "tts-a", "tts-b")
    response = await client.post("/api/v1/audio/speech", json=SPEECH)
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "unknown voice"
    assert len(calls) == 1


async def test_every_instance_unreachable_gives_502(
    client: AsyncClient, registry: InMemoryRegistryStore
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    await make_pool(registry, handler, "tts-a", "tts-b")
    response = await client.post("/api/v1/audio/speech", json=SPEECH)
    assert response.status_code == 502
    assert "could be reached" in response.json()["error"]["message"]


async def test_dead_instances_are_not_used(
    client: AsyncClient, registry: InMemoryRegistryStore
) -> None:
    await make_pool(registry, audio, "tts-a")
    await registry.remove("tts-a")
    assert (await client.post("/api/v1/audio/speech", json=SPEECH)).status_code == 503


async def test_voices_route(client: AsyncClient, registry: InMemoryRegistryStore) -> None:
    body = {"object": "list", "data": [{"id": "fr_FR-x"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/audio/voices"
        return httpx.Response(200, json=body)

    await make_pool(registry, handler, "tts-a")
    assert (await client.get("/api/v1/audio/voices")).json() == body


@pytest.mark.parametrize("path", ["/api/v1/audio/speech"])
async def test_get_on_speech_is_not_allowed(client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 405

"""Registry: stores, routes, token."""

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.config import settings
from app.db import Base
from app.services.registry import InMemoryRegistryStore, RegisteredInstance, RegistryStore
from app.services.registry_sql import SqlRegistryStore
from app.services.state import utcnow

WS = "ws://asr:8080/v1/audio/transcriptions/realtime"


@pytest_asyncio.fixture(params=["memory", "sql"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[RegistryStore]:
    if request.param == "memory":
        yield InMemoryRegistryStore()
        return
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield SqlRegistryStore(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


def instance(
    id_: str, kind: str = "nemo", priority: int = 0, age_s: float = 0
) -> RegisteredInstance:
    item = RegisteredInstance(id_, kind, WS, 8, priority)
    item.last_seen = utcnow() - timedelta(seconds=age_s)
    return item


async def test_upsert_registers_then_refreshes(store: RegistryStore) -> None:
    await store.upsert(instance("a", age_s=20))
    first = (await store.list_alive(30))[0]
    refreshed = instance("a")
    refreshed.max_streams = 12
    await store.upsert(refreshed)

    [alive] = await store.list_alive(30)
    assert alive.max_streams == 12
    assert alive.last_seen > first.last_seen
    assert alive.registered_at == first.registered_at


async def test_list_alive_filters_ttl_and_kind_and_orders(store: RegistryStore) -> None:
    await store.upsert(instance("b", priority=1))
    await store.upsert(instance("a", priority=1))
    await store.upsert(instance("z", priority=0))
    await store.upsert(instance("v", kind="vosk"))
    await store.upsert(instance("dead", age_s=45))

    assert [i.id for i in await store.list_alive(30)] == ["v", "z", "a", "b"]
    assert [i.id for i in await store.list_alive(30, kinds=("nemo",))] == ["z", "a", "b"]
    assert "dead" in [i.id for i in await store.list_alive(60)]


async def test_remove_and_prune(store: RegistryStore) -> None:
    await store.upsert(instance("a"))
    await store.upsert(instance("dead", age_s=400))
    assert await store.remove("a") is True
    assert await store.remove("a") is False
    assert await store.prune(300) == 1
    assert await store.list_alive(1000) == []


async def test_register_heartbeat_list_unregister(client: AsyncClient) -> None:
    body = {"kind": "vosk", "url": WS, "max_streams": 12, "priority": 2}
    response = await client.put("/api/v1/registry/instances/vosk-1", json=body)
    assert response.status_code == 200
    assert response.json() == {"id": "vosk-1", "ttl_s": settings.REGISTRY_TTL_S}
    assert (await client.put("/api/v1/registry/instances/vosk-1", json=body)).status_code == 200

    [listed] = (await client.get("/api/v1/registry/instances")).json()
    assert (listed["id"], listed["kind"], listed["max_streams"], listed["priority"]) == (
        "vosk-1",
        "vosk",
        12,
        2,
    )
    assert listed["age_s"] >= 0

    assert (await client.delete("/api/v1/registry/instances/vosk-1")).status_code == 204
    assert (await client.delete("/api/v1/registry/instances/vosk-1")).status_code == 204
    assert (await client.get("/api/v1/registry/instances")).json() == []


async def test_list_can_be_filtered_by_kind(client: AsyncClient) -> None:
    await client.put(
        "/api/v1/registry/instances/t",
        json={"kind": "tts", "url": "http://t:8080", "max_streams": 4},
    )
    await client.put(
        "/api/v1/registry/instances/v", json={"kind": "vosk", "url": WS, "max_streams": 4}
    )
    [tts] = (await client.get("/api/v1/registry/instances?kind=tts")).json()
    assert tts["id"] == "t"
    assert (await client.get("/api/v1/registry/instances?kind=nope")).status_code == 400


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "gpu", "url": WS, "max_streams": 1},
        {"kind": "tts", "url": WS, "max_streams": 1},  # a TTS server announces an http URL
        {"kind": "vosk", "url": "http://a:1", "max_streams": 1},
        {"kind": "vosk", "url": WS, "max_streams": 0},
        {"kind": "vosk", "max_streams": 1},
    ],
)
async def test_bad_registrations_are_refused(client: AsyncClient, body: dict[str, object]) -> None:
    assert (await client.put("/api/v1/registry/instances/x", json=body)).status_code == 422


async def test_bad_instance_id(client: AsyncClient) -> None:
    body = {"kind": "vosk", "url": WS, "max_streams": 1}
    assert (await client.put("/api/v1/registry/instances/a b", json=body)).status_code == 422


async def test_token_is_required_when_set(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "REGISTRY_TOKEN", "s3cret")
    body = {"kind": "vosk", "url": WS, "max_streams": 1}
    url = "/api/v1/registry/instances/a"
    assert (await client.put(url, json=body)).status_code == 401
    assert (
        await client.put(url, json=body, headers={"Authorization": "Bearer no"})
    ).status_code == 401
    assert (await client.get("/api/v1/registry/instances")).status_code == 401
    assert (await client.delete(url)).status_code == 401
    good = {"Authorization": "Bearer s3cret"}
    assert (await client.put(url, json=body, headers=good)).status_code == 200
    assert (await client.get("/api/v1/registry/instances", headers=good)).status_code == 200
    assert (await client.delete(url, headers=good)).status_code == 204

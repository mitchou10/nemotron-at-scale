"""Status page history: sampling, store contract, aggregation and routes."""

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db import Base
from app.main import app
from app.services.discovery import StaticDiscovery, parse_endpoints
from app.services.gateway import Gateway
from app.services.history import summarize
from app.services.state import (
    InMemoryStateStore,
    InstanceSample,
    StateStore,
    StreamState,
    StreamStatus,
    utcnow,
)
from app.services.state_sql import SqlStateStore


@pytest_asyncio.fixture(params=["memory", "sql"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[StateStore]:
    if request.param == "memory":
        yield InMemoryStateStore()
        return
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield SqlStateStore(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


def sample(
    instance: str, age_h: float, *, up: bool = True, active: int = 0, latency: float | None = 10.0
):
    return InstanceSample(instance, up, active, 8, latency, at=utcnow() - timedelta(hours=age_h))


async def test_samples_are_listed_since_and_pruned(store: StateStore) -> None:
    for age in (30, 5, 1):
        await store.save_sample(sample("a:1", age))
    recent = await store.list_samples(utcnow() - timedelta(hours=6))
    assert len(recent) == 2
    assert recent[0].at < recent[1].at
    assert await store.prune_samples(utcnow() - timedelta(hours=24)) == 1
    assert len(await store.list_samples(utcnow() - timedelta(hours=100))) == 2


async def test_streams_can_be_filtered_by_start(store: StateStore) -> None:
    old = StreamState("c", "a:1", started_at=utcnow() - timedelta(hours=30))
    new = StreamState("c", "a:1")
    await store.save_stream(old)
    await store.save_stream(new)
    assert [s.id for s in await store.list_streams(since=utcnow() - timedelta(hours=1))] == [new.id]


def test_summarize_buckets_uptime_and_latency() -> None:
    until = utcnow()
    since = until - timedelta(hours=2)
    samples = [
        sample("a:1", 1.5, up=True, active=3, latency=10),
        sample("a:1", 1.4, up=True, active=1, latency=30),
        sample("a:1", 0.5, up=False, latency=None),
        sample("a:1", 5, up=True),  # before the window: ignored
    ]
    streams = [
        StreamState("c", "a:1", status=StreamStatus.FAILED, failovers=2),
        StreamState("c", "a:1", status=StreamStatus.RUNNING),
    ]
    result = summarize(samples, streams, since=since, until=until, buckets=2)

    [worker] = result["instances"]
    assert worker["uptime_pct"] == pytest.approx(66.67)
    assert worker["avg_latency_ms"] == 20
    assert worker["peak_streams"] == 3
    assert [b["up_ratio"] for b in worker["buckets"]] == [1.0, 0.0]
    assert result["bucket_seconds"] == 3600
    assert result["streams"] == {
        "started": 2,
        "active": 1,
        "ended": 0,
        "failed": 1,
        "interrupted": 0,
        "failovers": 2,
    }


def test_summarize_without_data() -> None:
    until = utcnow()
    result = summarize([], [], since=until - timedelta(hours=1), until=until, buckets=4)
    assert result["instances"] == []
    assert result["streams"]["started"] == 0


async def test_gateway_samples_once_per_interval() -> None:
    store = InMemoryStateStore()
    endpoints = parse_endpoints("ws://a:8080/v1/audio/transcriptions/realtime", 4)
    gateway = Gateway(StaticDiscovery(endpoints), store=store, history_interval=3600)
    gateway._client = None  # no probing in this test: instances stay unhealthy
    await gateway._discover()
    await gateway._record_history()
    await gateway._record_history()  # within the interval: no second sample
    samples = await store.list_samples(utcnow() - timedelta(hours=1))
    assert [(s.instance, s.up) for s in samples] == [("a:8080", False)]


async def test_gateway_history_can_be_disabled() -> None:
    store = InMemoryStateStore()
    endpoints = parse_endpoints("ws://a:8080/v1/audio/transcriptions/realtime", 4)
    gateway = Gateway(StaticDiscovery(endpoints), store=store, history_interval=0)
    await gateway._discover()
    await gateway._record_history()
    assert await store.list_samples(utcnow() - timedelta(hours=1)) == []


async def test_history_route_is_empty_without_gateway(client: AsyncClient) -> None:
    app.state.transcriber = None
    response = await client.get("/api/v1/asr/history?hours=1&buckets=4")
    assert response.status_code == 200
    assert response.json()["instances"] == []


async def test_history_route_validates_parameters(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/asr/history?hours=0")).status_code == 422
    assert (await client.get("/api/v1/asr/history?buckets=1000")).status_code == 422


async def test_status_page_is_served(client: AsyncClient) -> None:
    page = await client.get("/status/")
    assert page.status_code == 200
    assert "Nemotron" in page.text
    assert (await client.get("/status/app.js")).status_code == 200

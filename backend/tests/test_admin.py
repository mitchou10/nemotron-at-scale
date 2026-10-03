"""Admin statistics: call log, aggregation, routes, token."""

from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.config import settings
from app.db import Base
from app.main import app
from app.services import stats
from app.services.calls import (
    InMemoryTtsCallStore,
    TtsCallRecord,
    TtsCallStore,
    matches_status,
)
from app.services.calls_sql import SqlTtsCallStore
from app.services.registry import InMemoryRegistryStore, RegisteredInstance
from app.services.state import InMemoryStateStore, StreamState, StreamStatus, utcnow
from app.services.tts_pool import TtsPool
from tests.discovery_helpers import ListDiscovery


@pytest_asyncio.fixture(params=["memory", "sql"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[TtsCallStore]:
    if request.param == "memory":
        yield InMemoryTtsCallStore()
        return
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield SqlTtsCallStore(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


def call(status: int = 200, age_h: float = 0, **kw: object) -> TtsCallRecord:
    defaults: dict[str, object] = {"instance": "tts-a", "voice": "fr_FR-x", "duration_ms": 400}
    return TtsCallRecord(
        status,
        **{**defaults, **kw},
        at=utcnow() - timedelta(hours=age_h),  # type: ignore[arg-type]
    )


async def test_call_store_lists_newest_first_filters_and_prunes(store: TtsCallStore) -> None:
    await store.add(call(200, age_h=5, characters=1))
    await store.add(call(429, age_h=2))
    await store.add(call(503, age_h=1))
    await store.add(call(200, age_h=0.5, characters=2))

    since = utcnow() - timedelta(hours=3)
    recent = await store.list_since(since)
    assert [c.status_code for c in recent] == [200, 503, 429]
    assert [c.status_code for c in await store.list_since(since, limit=2)] == [200, 503]
    assert [c.status_code for c in await store.list_since(since, status_class="ok")] == [200]
    assert [c.status_code for c in await store.list_since(since, status_class="client_error")] == [
        429
    ]
    assert [c.status_code for c in await store.list_since(since, status_class="error")] == [503]

    assert await store.prune(utcnow() - timedelta(hours=3)) == 1
    assert len(await store.list_since(utcnow() - timedelta(days=1))) == 3


def test_status_classes() -> None:
    assert matches_status(204, "ok") and not matches_status(404, "ok")
    assert matches_status(404, "client_error") and not matches_status(500, "client_error")
    assert matches_status(500, "error") and matches_status(1, None)


def test_percentile() -> None:
    assert stats.percentile([], 95) is None
    assert stats.percentile([5], 95) == 5
    assert stats.percentile([float(n) for n in range(1, 101)], 95) == 95
    assert stats.percentile([3.0, 1.0, 2.0], 50) == 2


def test_tts_summary() -> None:
    calls = [
        call(200, duration_ms=100, first_byte_ms=20, characters=10, audio_bytes=1000),
        call(200, duration_ms=300, first_byte_ms=40, characters=30, audio_bytes=3000, voice="v2"),
        call(429),
        call(400),
        call(502, instance=None),
    ]
    summary = stats.tts_summary(calls)
    assert (summary["requests"], summary["ok"], summary["success_rate_pct"]) == (5, 2, 40.0)
    assert (summary["rate_limited"], summary["client_errors"], summary["server_errors"]) == (
        1,
        1,
        1,
    )
    assert (summary["characters"], summary["audio_bytes"]) == (40 + 0, 4000)
    assert (summary["avg_duration_ms"], summary["p95_duration_ms"]) == (200.0, 300.0)
    assert summary["avg_first_byte_ms"] == 30.0
    assert summary["by_voice"] == [{"voice": "fr_FR-x", "count": 1}, {"voice": "v2", "count": 1}]
    assert summary["by_instance"] == [{"instance": "tts-a", "count": 2}]


def test_tts_summary_without_calls() -> None:
    summary = stats.tts_summary([])
    assert summary["requests"] == 0
    assert summary["success_rate_pct"] is None
    assert summary["p95_duration_ms"] is None


def stream(status: StreamStatus, client: str = "c", failovers: int = 0, age_s: float = 60):  # type: ignore[no-untyped-def]
    started = utcnow() - timedelta(seconds=age_s)
    item = StreamState(client, "a:1", status, failovers, started_at=started, updated_at=utcnow())
    if status not in (StreamStatus.RUNNING, StreamStatus.RECOVERING):
        item.ended_at = started + timedelta(seconds=30)
    return item


def test_stt_summary() -> None:
    streams = [
        stream(StreamStatus.ENDED, "alice"),
        stream(StreamStatus.ENDED, "alice", failovers=1),
        stream(StreamStatus.FAILED, "bob"),
        stream(StreamStatus.RUNNING, "carol"),
    ]
    summary = stats.stt_summary(streams, active_now=1)
    assert (summary["streams"], summary["active"], summary["ended"], summary["failed"]) == (
        4,
        1,
        2,
        1,
    )
    assert (summary["failovers"], summary["unique_clients"]) == (1, 3)
    assert (summary["avg_duration_s"], summary["total_duration_s"]) == (30.0, 90.0)


def test_timeseries_buckets() -> None:
    until = utcnow()
    since = until - timedelta(hours=2)
    result = stats.timeseries(
        [stream(StreamStatus.ENDED, age_s=5400), stream(StreamStatus.FAILED, age_s=60)],
        [call(200, age_h=1.5, characters=7), call(200, age_h=1.4), call(500, age_h=0.1)],
        since=since,
        until=until,
        buckets=2,
    )
    first, second = result["buckets"]
    assert (first["stt_streams"], second["stt_streams"], second["stt_failed"]) == (1, 1, 1)
    assert (first["tts_ok"], first["tts_characters"], second["tts_failed"]) == (2, 7, 1)
    assert first["tts_avg_duration_ms"] == 400.0
    assert result["bucket_seconds"] == 3600


async def test_overview_without_anything(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/admin/overview")).json()
    assert body["stt"]["streams"] == 0
    assert body["tts"]["requests"] == 0
    assert body["workers"] == {"total": 0, "healthy": 0, "by_kind": {}, "asr_enabled": False}


async def test_overview_timeseries_lists_and_workers(client: AsyncClient) -> None:
    store = InMemoryStateStore()
    app.state.transcriber = type(
        "G", (), {"store": store, "status": lambda self: [], "start": None, "stop": None}
    )()
    await store.save_stream(stream(StreamStatus.ENDED, "alice"))
    await store.save_stream(stream(StreamStatus.RUNNING, "bob"))
    await app.state.tts_calls.add(call(200, characters=12, first_byte_ms=30))
    await app.state.tts_calls.add(call(503))
    await app.state.registry.upsert(RegisteredInstance("tts-a", "tts", "http://tts-a:8080", 4))
    await app.state.registry.upsert(
        RegisteredInstance("v1", "vosk", "ws://v1:8080/v1/audio/transcriptions/realtime", 12)
    )
    try:
        overview = (await client.get("/api/v1/admin/overview?hours=1")).json()
        assert overview["stt"]["streams"] == 2 and overview["stt"]["active"] == 1
        assert overview["tts"]["requests"] == 2 and overview["tts"]["server_errors"] == 1
        assert overview["workers"]["by_kind"] == {
            "tts": {"total": 1, "healthy": 1},
            "vosk": {"total": 1, "healthy": 0},  # registered, not probed by the gateway yet
        }

        series = (await client.get("/api/v1/admin/timeseries?hours=1&buckets=4")).json()
        assert len(series["buckets"]) == 4
        assert sum(b["tts_ok"] for b in series["buckets"]) == 1

        streams = (await client.get("/api/v1/admin/stt/streams")).json()
        assert [s["client_id"] for s in streams] == ["bob", "alice"]
        active = (await client.get("/api/v1/admin/stt/streams?state=active")).json()
        assert [s["client_id"] for s in active] == ["bob"]
        assert (await client.get("/api/v1/admin/stt/streams?state=nope")).status_code == 400

        failed = (await client.get("/api/v1/admin/tts/calls?result=error")).json()
        assert [c["status_code"] for c in failed] == [503]
        assert len((await client.get("/api/v1/admin/tts/calls?limit=1")).json()) == 1
        assert (await client.get("/api/v1/admin/tts/calls?result=nope")).status_code == 422

        workers = (await client.get("/api/v1/admin/workers")).json()
        assert {w["id"]: (w["kind"], w["healthy"]) for w in workers} == {
            "tts-a": ("tts", True),
            "v1": ("vosk", False),
        }
    finally:
        app.state.transcriber = None


async def test_workers_merge_the_gateway_view(client: AsyncClient) -> None:
    status_row = {
        "instance": "v1:8080",
        "healthy": True,
        "latency_ms": 12.5,
        "active_streams": 3,
        "max_streams": 12,
    }
    app.state.transcriber = type(
        "G", (), {"store": InMemoryStateStore(), "status": lambda self: [status_row]}
    )()
    await app.state.registry.upsert(
        RegisteredInstance("v1", "vosk", "ws://v1:8080/v1/audio/transcriptions/realtime", 12)
    )
    try:
        [worker] = (await client.get("/api/v1/admin/workers")).json()
    finally:
        app.state.transcriber = None
    assert (worker["healthy"], worker["latency_ms"], worker["active"]) == (True, 12.5, 3)


async def test_tts_load_shows_in_the_workers(client: AsyncClient) -> None:
    registry: InMemoryRegistryStore = app.state.registry
    await registry.upsert(RegisteredInstance("tts-a", "tts", "http://tts-a:8080", 4))
    pool = TtsPool(registry, 30, client=httpx.AsyncClient())
    pool._in_flight["tts-a"] = 2
    app.state.tts_pool = pool
    [worker] = (await client.get("/api/v1/admin/workers")).json()
    assert worker["active"] == 2


async def test_token_is_required_when_set(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "admin-secret")
    for path in ("overview", "timeseries", "workers", "stt/streams", "tts/calls"):
        assert (await client.get(f"/api/v1/admin/{path}")).status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert (await client.get("/api/v1/admin/overview", headers=wrong)).status_code == 401
    good = {"Authorization": "Bearer admin-secret"}
    assert (await client.get("/api/v1/admin/overview", headers=good)).status_code == 200


async def test_list_has_no_gateway_when_asr_is_disabled(client: AsyncClient) -> None:
    app.state.transcriber = None
    assert (await client.get("/api/v1/admin/stt/streams")).json() == []
    assert ListDiscovery([]) is not None

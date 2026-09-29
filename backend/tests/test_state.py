"""State store contract tests (in-memory and SQL implementations) and StreamRecorder."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db import Base
from app.services.state import (
    InMemoryStateStore,
    InstanceState,
    InstanceStatus,
    StateStore,
    StreamRecorder,
    StreamState,
    StreamStatus,
    safely,
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


def instance(key: str, priority: int = 0, **kw: object) -> InstanceState:
    return InstanceState(key, f"ws://{key}", InstanceStatus.UP, priority, 8, **kw)  # type: ignore[arg-type]


async def test_state_store_is_abstract() -> None:
    with pytest.raises(TypeError):
        StateStore()  # type: ignore[abstract]


async def test_instances_are_upserted_and_ordered(store: StateStore) -> None:
    await store.save_instance(instance("b:1", priority=1))
    await store.save_instance(instance("a:1", priority=1, active_streams=2, latency_ms=12.5))
    await store.save_instance(instance("z:1", priority=0))
    await store.save_instance(
        InstanceState("b:1", "ws://b:1", InstanceStatus.DOWN, 1, 8, active_streams=0)
    )
    saved = await store.list_instances()
    assert [(s.key, s.status) for s in saved] == [
        ("z:1", InstanceStatus.UP),
        ("a:1", InstanceStatus.UP),
        ("b:1", InstanceStatus.DOWN),
    ]
    a = saved[1]
    assert (a.active_streams, a.latency_ms, a.max_streams, a.url) == (2, 12.5, 8, "ws://a:1")


async def test_streams_are_upserted_and_filtered(store: StateStore) -> None:
    running = StreamState("alice", "a:1")
    done = StreamState("bob", "b:1")
    await store.save_stream(running)
    await store.save_stream(done)
    done.status = StreamStatus.ENDED
    await store.save_stream(done)

    everything = await store.list_streams()
    assert {(s.client_id, s.instance, s.status) for s in everything} == {
        ("alice", "a:1", StreamStatus.RUNNING),
        ("bob", "b:1", StreamStatus.ENDED),
    }
    active = await store.list_streams(active_only=True)
    assert [s.client_id for s in active] == ["alice"]


async def test_recovering_stream_counts_as_active(store: StateStore) -> None:
    await store.save_stream(StreamState("alice", "a:1", StreamStatus.RECOVERING, failovers=1))
    [stream] = await store.list_streams(active_only=True)
    assert (stream.status, stream.failovers) == (StreamStatus.RECOVERING, 1)


async def test_interrupt_active_streams(store: StateStore) -> None:
    await store.save_stream(StreamState("alice", "a:1"))
    await store.save_stream(StreamState("bob", "a:1", StreamStatus.RECOVERING))
    await store.save_stream(StreamState("carol", "a:1", StreamStatus.ENDED))
    assert await store.interrupt_active_streams() == 2
    statuses = {s.client_id: s.status for s in await store.list_streams()}
    assert statuses == {
        "alice": StreamStatus.INTERRUPTED,
        "bob": StreamStatus.INTERRUPTED,
        "carol": StreamStatus.ENDED,
    }
    interrupted = [s for s in await store.list_streams() if s.client_id == "alice"]
    assert interrupted[0].ended_at is not None
    assert await store.interrupt_active_streams() == 0


async def test_memory_store_returns_copies() -> None:
    store = InMemoryStateStore()
    state = StreamState("alice", "a:1")
    await store.save_stream(state)
    state.status = StreamStatus.FAILED
    assert (await store.list_streams())[0].status == StreamStatus.RUNNING


async def test_recorder_follows_the_stream_life_cycle(store: StateStore) -> None:
    recorder = StreamRecorder(store, "alice")
    await recorder.started("a:1")
    [stream] = await store.list_streams()
    assert (stream.client_id, stream.instance, stream.status) == (
        "alice",
        "a:1",
        StreamStatus.RUNNING,
    )

    await recorder.recovering()
    assert (await store.list_streams())[0].status == StreamStatus.RECOVERING

    await recorder.resumed("b:1", 1)
    [stream] = await store.list_streams()
    assert (stream.instance, stream.status, stream.failovers) == (
        "b:1",
        StreamStatus.RUNNING,
        1,
    )

    await recorder.finished(StreamStatus.ENDED)
    [stream] = await store.list_streams()
    assert stream.status == StreamStatus.ENDED
    assert stream.ended_at is not None

    await recorder.finished(StreamStatus.FAILED)
    assert (await store.list_streams())[0].status == StreamStatus.ENDED


async def test_recorder_ignores_updates_before_start() -> None:
    store = InMemoryStateStore()
    recorder = StreamRecorder(store, "alice")
    await recorder.recovering()
    await recorder.finished(StreamStatus.ENDED)
    assert await store.list_streams() == []


class BrokenStore(InMemoryStateStore):
    async def save_stream(self, state: StreamState) -> None:
        raise RuntimeError("database down")


async def test_recorder_survives_storage_errors() -> None:
    recorder = StreamRecorder(BrokenStore(), "alice")
    await recorder.started("a:1")
    await recorder.finished(StreamStatus.ENDED)


async def test_safely_swallows_errors() -> None:
    async def boom() -> None:
        raise RuntimeError("nope")

    await safely(boom(), "do something")

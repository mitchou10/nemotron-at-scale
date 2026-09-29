"""State of ASR instances and audio streams (who is on which instance, running or not)."""

import dataclasses
import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


class StreamStatus(StrEnum):
    RUNNING = "running"
    RECOVERING = "recovering"
    ENDED = "ended"
    FAILED = "failed"
    INTERRUPTED = "interrupted"  # left running by a backend that stopped


ACTIVE_STREAM_STATUSES = (StreamStatus.RUNNING, StreamStatus.RECOVERING)


class InstanceStatus(StrEnum):
    UP = "up"
    DOWN = "down"
    DRAINING = "draining"  # no longer discovered, still serving its streams
    GONE = "gone"


@dataclass
class InstanceState:
    key: str
    url: str
    status: InstanceStatus
    priority: int
    max_streams: int
    active_streams: int = 0
    latency_ms: float | None = None
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class StreamState:
    client_id: str
    instance: str
    status: StreamStatus = StreamStatus.RUNNING
    failovers: int = 0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    ended_at: datetime | None = None


class StateStore(ABC):
    @abstractmethod
    async def save_instance(self, state: InstanceState) -> None: ...

    @abstractmethod
    async def save_stream(self, state: StreamState) -> None: ...

    @abstractmethod
    async def list_instances(self) -> list[InstanceState]: ...

    @abstractmethod
    async def list_streams(self, *, active_only: bool = False) -> list[StreamState]: ...

    @abstractmethod
    async def interrupt_active_streams(self) -> int:
        """Mark streams left running by a previous process as interrupted; return the count."""


class InMemoryStateStore(StateStore):
    def __init__(self) -> None:
        self._instances: dict[str, InstanceState] = {}
        self._streams: dict[str, StreamState] = {}

    async def save_instance(self, state: InstanceState) -> None:
        self._instances[state.key] = dataclasses.replace(state)

    async def save_stream(self, state: StreamState) -> None:
        self._streams[state.id] = dataclasses.replace(state)

    async def list_instances(self) -> list[InstanceState]:
        return sorted(self._instances.values(), key=lambda s: (s.priority, s.key))

    async def list_streams(self, *, active_only: bool = False) -> list[StreamState]:
        streams = sorted(self._streams.values(), key=lambda s: s.started_at)
        if active_only:
            return [s for s in streams if s.status in ACTIVE_STREAM_STATUSES]
        return streams

    async def interrupt_active_streams(self) -> int:
        active = await self.list_streams(active_only=True)
        for stream in active:
            stream.status = StreamStatus.INTERRUPTED
            stream.ended_at = stream.updated_at = utcnow()
            self._streams[stream.id] = stream
        return len(active)


class StreamRecorder:
    """Keeps the stored state of one stream up to date; storage errors never break the stream."""

    def __init__(self, store: StateStore, client_id: str) -> None:
        self._store = store
        self._client_id = client_id
        self._state: StreamState | None = None

    async def started(self, instance: str) -> None:
        self._state = StreamState(self._client_id, instance)
        await self._save()

    async def recovering(self) -> None:
        await self._update(status=StreamStatus.RECOVERING)

    async def resumed(self, instance: str, failovers: int) -> None:
        await self._update(status=StreamStatus.RUNNING, instance=instance, failovers=failovers)

    async def finished(self, status: StreamStatus) -> None:
        if self._state and self._state.status in ACTIVE_STREAM_STATUSES:
            await self._update(status=status, ended_at=utcnow())

    async def _update(self, **changes: object) -> None:
        if self._state:
            self._state = dataclasses.replace(self._state, updated_at=utcnow(), **changes)  # type: ignore[arg-type]
            await self._save()

    async def _save(self) -> None:
        assert self._state is not None
        await safely(self._store.save_stream(self._state), "save stream state")


async def safely(awaitable: Awaitable[object], what: str) -> None:
    """Await a storage call, logging instead of raising."""
    try:
        await awaitable
    except Exception:
        logger.exception("could not %s", what)

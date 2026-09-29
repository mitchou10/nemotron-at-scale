"""Gateway spreading audio streams over several `nemo-speech serve` instances.

Instances come from a `Discovery` (static list, DNS...). Every instance is probed
(`GET /ready`) to measure latency. Streams fill instances one after the other: a new stream goes
to the first healthy instance (by discovery priority, then address) that has not reached its
stream limit. An optional `max_latency_ms` skips slow instances unless every free instance is
slow, in which case the fastest one is used. Instances and streams are recorded in a
`StateStore` (who is on which instance, running or not).
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.services.discovery import DiscoveredInstance, Discovery
from app.services.metrics import GatewayMetrics
from app.services.nemo_speech import NemoSpeechTranscriber
from app.services.resilient import ResilientSession
from app.services.state import (
    InMemoryStateStore,
    InstanceState,
    InstanceStatus,
    StateStore,
    StreamRecorder,
    safely,
)
from app.services.transcription import (
    TranscriberBusyError,
    TranscriberUnavailableError,
    TranscriptEvent,
    TranscriptionSession,
)

logger = logging.getLogger(__name__)

EWMA_ALPHA = 0.3


@dataclass
class Instance:
    key: str
    priority: int
    max_streams: int
    url: str
    probe_url: str
    transcriber: NemoSpeechTranscriber
    healthy: bool = False
    present: bool = True
    latency_ms: float | None = None
    active: int = 0

    @property
    def has_capacity(self) -> bool:
        return self.active < self.max_streams


class _TrackedSession:
    """Session wrapper that releases the instance slot and reports failures."""

    def __init__(
        self,
        inner: TranscriptionSession,
        instance: Instance,
        on_release: Callable[[Instance], Awaitable[None]],
        metrics: GatewayMetrics,
    ) -> None:
        self._inner = inner
        self._instance = instance
        self._on_release = on_release
        self._metrics = metrics
        self._released = False
        self._failed = False
        self._first_audio_at: float | None = None
        self._first_result_seen = False

    @property
    def key(self) -> str:
        return self._instance.key

    def fail(self) -> None:
        self._instance.healthy = False
        if not self._failed:
            self._failed = True
            self._metrics.instance_failures.labels(self._instance.key).inc()

    async def send_audio(self, pcm: bytes) -> None:
        if self._first_audio_at is None:
            self._first_audio_at = time.perf_counter()
        try:
            await self._inner.send_audio(pcm)
        except TranscriberUnavailableError:
            self.fail()
            raise

    async def end(self) -> None:
        try:
            await self._inner.end()
        except TranscriberUnavailableError:
            self.fail()
            raise

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        try:
            async for event in self._inner.events():
                self._observe_first_result(event)
                yield event
        except TranscriberUnavailableError:
            self.fail()
            raise

    def _observe_first_result(self, event: TranscriptEvent) -> None:
        if self._first_result_seen or self._first_audio_at is None or event.type == "committed":
            return
        self._first_result_seen = True
        elapsed = time.perf_counter() - self._first_audio_at
        self._metrics.first_result_seconds.labels(self._instance.key).observe(elapsed)

    async def close(self) -> None:
        if not self._released:
            self._released = True
            self._instance.active -= 1
            await self._on_release(self._instance)
        await self._inner.close()


class Gateway:
    def __init__(
        self,
        discovery: Discovery,
        api_key: str | None = None,
        *,
        store: StateStore | None = None,
        metrics: GatewayMetrics | None = None,
        probe_interval: float = 5.0,
        max_latency_ms: float = 0.0,
        buffer_seconds: int = 30,
        max_failovers: int = 2,
    ) -> None:
        self._discovery = discovery
        self._api_key = api_key
        self.store: StateStore = store or InMemoryStateStore()
        self.metrics = metrics or GatewayMetrics()
        self._probe_interval = probe_interval
        self._max_latency_ms = max_latency_ms
        self._buffer_seconds = buffer_seconds
        self._max_failovers = max_failovers
        self._instances: dict[str, Instance] = {}
        self._client: httpx.AsyncClient | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=2.0)
        await safely(self.store.interrupt_active_streams(), "interrupt stale streams")
        await self.refresh()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._client:
            await self._client.aclose()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._probe_interval)
            await self.refresh()

    async def refresh(self) -> None:
        """Re-discover instances, re-measure their latency and save their state."""
        await self._discover()
        await asyncio.gather(*(self._probe(i) for i in self._instances.values()))
        await asyncio.gather(*(self._save(i) for i in self._instances.values()))

    async def _discover(self) -> None:
        found = {d.key: d for d in await self._discovery.discover()}
        for key, discovered in found.items():
            if key in self._instances:
                self._instances[key].present = True
            else:
                self._instances[key] = self._new_instance(discovered)
        for key, instance in list(self._instances.items()):
            if key in found:
                continue
            instance.present = False
            if instance.active == 0:
                del self._instances[key]
                await self._save(instance, gone=True)

    def _new_instance(self, d: DiscoveredInstance) -> Instance:
        return Instance(
            d.key,
            d.priority,
            d.max_streams,
            d.url,
            d.probe_url,
            NemoSpeechTranscriber(d.url, self._api_key),
        )

    async def _save(self, instance: Instance, *, gone: bool = False) -> None:
        if gone:
            status = InstanceStatus.GONE
        elif not instance.present:
            status = InstanceStatus.DRAINING
        else:
            status = InstanceStatus.UP if instance.healthy else InstanceStatus.DOWN
        state = InstanceState(
            key=instance.key,
            url=instance.url,
            status=status,
            priority=instance.priority,
            max_streams=instance.max_streams,
            active_streams=instance.active,
            latency_ms=None if instance.latency_ms is None else round(instance.latency_ms, 1),
        )
        await safely(self.store.save_instance(state), "save instance state")
        if gone:
            self.metrics.forget_instance(instance.key)
        else:
            self.metrics.publish_instance(
                instance.key,
                up=status == InstanceStatus.UP,
                latency_ms=state.latency_ms,
                active=instance.active,
                max_streams=instance.max_streams,
            )

    async def _probe(self, instance: Instance) -> None:
        assert self._client is not None
        started = time.perf_counter()
        try:
            response = await self._client.get(instance.probe_url)
            ok = response.status_code == 200
        except httpx.HTTPError:
            ok = False
        if not ok:
            instance.healthy = False
            self.metrics.probe_failures.labels(instance.key).inc()
            return
        sample = (time.perf_counter() - started) * 1000
        self.metrics.probe_seconds.labels(instance.key).observe(sample / 1000)
        previous = instance.latency_ms
        instance.latency_ms = (
            sample if previous is None else (1 - EWMA_ALPHA) * previous + EWMA_ALPHA * sample
        )
        instance.healthy = True

    async def open_session(self, client_id: str = "unknown") -> TranscriptionSession:
        first = await self._open_tracked(set())
        recorder = StreamRecorder(self.store, client_id)
        await recorder.started(first.key)
        return ResilientSession(
            self._open_tracked,
            first,
            buffer_seconds=self._buffer_seconds,
            max_failovers=self._max_failovers,
            observer=recorder,
        )

    async def _open_tracked(self, excluded: set[str]) -> _TrackedSession:
        usable = [
            i for i in self._instances.values() if i.healthy and i.present and i.key not in excluded
        ]
        candidates = self._order([i for i in usable if i.has_capacity])
        if not candidates:
            if usable:
                self.metrics.rejected.labels("busy").inc()
                raise TranscriberBusyError("all transcription instances are at capacity")
            self.metrics.rejected.labels("unavailable").inc()
            raise TranscriberUnavailableError("no healthy transcription instance")

        for instance in candidates:
            instance.active += 1
            opening = time.perf_counter()
            try:
                inner = await instance.transcriber.open_session()
            except TranscriberUnavailableError:
                instance.active -= 1
                instance.healthy = False
                self.metrics.open_failures.labels(instance.key).inc()
                await self._save(instance)
                logger.warning("asr instance %s unreachable, trying next", instance.key)
                continue
            self.metrics.open_seconds.labels(instance.key).observe(time.perf_counter() - opening)
            self.metrics.streams_opened.labels(instance.key).inc()
            if excluded:
                self.metrics.failovers.labels(instance.key).inc()
            await self._save(instance)
            return _TrackedSession(inner, instance, self._save, self.metrics)
        self.metrics.rejected.labels("unavailable").inc()
        raise TranscriberUnavailableError("all transcription instances failed")

    def _order(self, free: list[Instance]) -> list[Instance]:
        """Fill order: priority then address, slow instances only as a last resort."""
        free.sort(key=lambda i: (i.priority, i.key))
        if not self._max_latency_ms:
            return free
        fast = [i for i in free if (i.latency_ms or 0.0) <= self._max_latency_ms]
        slow = sorted((i for i in free if i not in fast), key=lambda i: i.latency_ms or 0.0)
        return fast + slow

    def status(self) -> list[dict[str, object]]:
        return [
            {
                "instance": i.key,
                "healthy": i.healthy and i.present,
                "priority": i.priority,
                "latency_ms": None if i.latency_ms is None else round(i.latency_ms, 1),
                "active_streams": i.active,
                "max_streams": i.max_streams,
            }
            for i in sorted(self._instances.values(), key=lambda i: i.key)
        ]

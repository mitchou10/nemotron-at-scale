"""Session that survives the loss of its transcription instance.

The audio of the segment being transcribed (everything since the last commit acknowledged by
the instance) is kept in a bounded buffer. When the instance drops, the session opens a new
one on another instance and replays the buffer, so transcription resumes without the client
noticing (its partial text simply restarts from the beginning of the segment).
"""

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from app.services.state import StreamStatus
from app.services.transcription import TranscriberUnavailableError, TranscriptEvent

logger = logging.getLogger(__name__)

BYTES_PER_SECOND = 16_000 * 2


class FailoverInner(Protocol):
    key: str

    def fail(self) -> None: ...

    async def send_audio(self, pcm: bytes) -> None: ...

    async def end(self) -> None: ...

    def events(self) -> AsyncIterator[TranscriptEvent]: ...

    async def close(self) -> None: ...


OpenInner = Callable[[set[str]], Awaitable[FailoverInner]]


class SessionObserver(Protocol):
    """Notified of the session life cycle (used to save which instance serves the stream)."""

    async def recovering(self) -> None: ...

    async def resumed(self, instance: str, failovers: int) -> None: ...

    async def finished(self, status: StreamStatus) -> None: ...


class ResilientSession:
    def __init__(
        self,
        open_inner: OpenInner,
        first: FailoverInner,
        *,
        buffer_seconds: int = 30,
        max_failovers: int = 2,
        observer: SessionObserver | None = None,
    ) -> None:
        self._observer = observer
        self._open_inner = open_inner
        self._inner = first
        self._generation = 0
        self._max_bytes = buffer_seconds * BYTES_PER_SECOND
        self._max_failovers = max_failovers
        self._failovers = 0
        self._excluded: set[str] = set()
        self._log: deque[bytes | None] = deque()  # audio chunks and None commit markers
        self._buffered = 0
        self._lock = asyncio.Lock()
        self._closing = False

    def _record(self, item: bytes | None) -> None:
        self._log.append(item)
        self._buffered += len(item or b"")
        while self._buffered > self._max_bytes:
            index = next(i for i, chunk in enumerate(self._log) if chunk is not None)
            self._buffered -= len(self._log[index] or b"")
            del self._log[index]

    def _acknowledge_commit(self) -> None:
        while self._log:
            chunk = self._log.popleft()
            if chunk is None:
                return
            self._buffered -= len(chunk)

    @property
    def instance_key(self) -> str:
        return self._inner.key

    @property
    def buffered_bytes(self) -> int:
        return self._buffered

    async def send_audio(self, pcm: bytes) -> None:
        inner, generation = self._inner, self._generation
        self._record(pcm)
        try:
            await inner.send_audio(pcm)
        except TranscriberUnavailableError:
            await self._recover(generation)

    async def end(self) -> None:
        inner, generation = self._inner, self._generation
        self._record(None)
        try:
            await inner.end()
        except TranscriberUnavailableError:
            await self._recover(generation)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            inner, generation = self._inner, self._generation
            try:
                async for event in inner.events():
                    if event.type == "committed":
                        self._acknowledge_commit()
                    else:
                        yield event
            except TranscriberUnavailableError:
                pass
            if self._closing:
                return
            inner.fail()
            await self._recover(generation)

    async def _recover(self, failed_generation: int) -> None:
        async with self._lock:
            if self._generation != failed_generation or self._closing:
                return
            failed = self._inner
            self._excluded.add(failed.key)
            if self._observer:
                await self._observer.recovering()
            with contextlib.suppress(Exception):
                await failed.close()
            while True:
                if self._failovers >= self._max_failovers:
                    await self._give_up()
                    raise TranscriberUnavailableError("transcription failover budget exhausted")
                self._failovers += 1
                try:
                    replacement = await self._open_inner(self._excluded)
                except TranscriberUnavailableError:
                    await self._give_up()
                    raise
                try:
                    await self._replay(replacement)
                except TranscriberUnavailableError:
                    self._excluded.add(replacement.key)
                    replacement.fail()
                    with contextlib.suppress(Exception):
                        await replacement.close()
                    continue
                logger.warning(
                    "transcription resumed on %s after losing %s", replacement.key, failed.key
                )
                self._inner = replacement
                self._generation += 1
                if self._observer:
                    await self._observer.resumed(replacement.key, self._failovers)
                return

    async def _give_up(self) -> None:
        if self._observer:
            await self._observer.finished(StreamStatus.FAILED)

    async def _replay(self, target: FailoverInner) -> None:
        index = 0
        while index < len(self._log):
            chunk = self._log[index]
            if chunk is None:
                await target.end()
            else:
                await target.send_audio(chunk)
            index += 1

    async def close(self) -> None:
        self._closing = True
        self._log.clear()
        self._buffered = 0
        await self._inner.close()
        if self._observer:
            await self._observer.finished(StreamStatus.ENDED)

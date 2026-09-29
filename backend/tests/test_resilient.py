"""ResilientSession tests with scripted fake instances."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.services.resilient import BYTES_PER_SECOND, FailoverInner, ResilientSession
from app.services.state import StreamStatus
from app.services.transcription import TranscriberUnavailableError, TranscriptEvent


class FakeInner:
    def __init__(self, key: str, *, dead: bool = False, replay_fails: bool = False) -> None:
        self.key = key
        self.dead = dead
        self.replay_fails = replay_fails
        self.sent: list[bytes | str] = []
        self.failed = False
        self.closed = False
        self.queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()

    def fail(self) -> None:
        self.failed = True

    async def send_audio(self, pcm: bytes) -> None:
        if self.dead or self.replay_fails:
            raise TranscriberUnavailableError("down")
        self.sent.append(pcm)

    async def end(self) -> None:
        if self.dead or self.replay_fails:
            raise TranscriberUnavailableError("down")
        self.sent.append("commit")

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            if self.dead:
                raise TranscriberUnavailableError("down")
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        self.closed = True


class Opener:
    def __init__(self, *inners: FakeInner) -> None:
        self._inners = list(inners)
        self.excluded_seen: list[set[str]] = []

    async def __call__(self, excluded: set[str]) -> FailoverInner:
        self.excluded_seen.append(set(excluded))
        if not self._inners:
            raise TranscriberUnavailableError("no instance left")
        return self._inners.pop(0)


def make(first: FakeInner, opener: Opener, **kw: int) -> ResilientSession:
    return ResilientSession(opener, first, **kw)


async def test_audio_replayed_on_send_failure() -> None:
    a, b = FakeInner("a"), FakeInner("b")
    session = make(a, Opener(b))
    await session.send_audio(b"1")
    a.dead = True
    await session.send_audio(b"2")
    await session.send_audio(b"3")
    assert b.sent == [b"1", b"2", b"3"]
    assert a.closed
    assert a.sent == [b"1"]


async def test_commit_replayed_at_its_position() -> None:
    a, b = FakeInner("a"), FakeInner("b")
    session = make(a, Opener(b))
    await session.send_audio(b"1")
    await session.end()
    a.dead = True
    await session.send_audio(b"2")
    assert b.sent == [b"1", "commit", b"2"]


async def test_failure_on_end_triggers_recovery() -> None:
    a, b = FakeInner("a"), FakeInner("b")
    session = make(a, Opener(b))
    await session.send_audio(b"1")
    a.dead = True
    await session.end()
    assert b.sent == [b"1", "commit"]


async def test_acknowledged_commit_trims_buffer() -> None:
    a, b = FakeInner("a"), FakeInner("b")
    session = make(a, Opener(b))
    await session.send_audio(b"1")
    await session.end()
    await session.send_audio(b"2")
    a.queue.put_nowait(TranscriptEvent("final", "one"))
    a.queue.put_nowait(TranscriptEvent("committed", ""))
    stream = session.events()
    assert await anext(stream) == TranscriptEvent("final", "one")
    a.queue.put_nowait(TranscriptEvent("partial", "two"))
    assert await anext(stream) == TranscriptEvent("partial", "two")
    a.dead = True
    await session.send_audio(b"3")
    assert b.sent == [b"2", b"3"]
    await stream.aclose()


async def test_buffer_is_bounded_and_keeps_newest_audio() -> None:
    a, b = FakeInner("a"), FakeInner("b")
    session = make(a, Opener(b), buffer_seconds=1)
    chunk = b"\x00" * (BYTES_PER_SECOND * 2 // 3)
    await session.send_audio(chunk)
    await session.end()
    await session.send_audio(chunk)
    await session.send_audio(chunk)
    a.dead = True
    await session.send_audio(b"x")
    assert b.sent == ["commit", chunk, b"x"]


async def test_empty_audio_chunk_is_not_mistaken_for_commit() -> None:
    a, b = FakeInner("a"), FakeInner("b")
    session = make(a, Opener(b))
    await session.send_audio(b"")
    a.dead = True
    await session.send_audio(b"1")
    assert b.sent == [b"", b"1"]


async def test_events_recover_when_stream_ends_unexpectedly() -> None:
    a, b = FakeInner("a"), FakeInner("b")
    session = make(a, Opener(b))
    await session.send_audio(b"1")
    a.queue.put_nowait(TranscriptEvent("partial", "x"))
    a.queue.put_nowait(None)
    b.queue.put_nowait(TranscriptEvent("partial", "y"))
    stream = session.events()
    assert await anext(stream) == TranscriptEvent("partial", "x")
    assert await anext(stream) == TranscriptEvent("partial", "y")
    assert a.failed
    assert b.sent == [b"1"]
    await stream.aclose()


async def test_events_recover_when_stream_raises() -> None:
    a, b = FakeInner("a", dead=True), FakeInner("b")
    session = make(a, Opener(b))
    b.queue.put_nowait(TranscriptEvent("partial", "y"))
    stream = session.events()
    assert await anext(stream) == TranscriptEvent("partial", "y")
    await stream.aclose()


async def test_events_end_quietly_when_closing() -> None:
    a = FakeInner("a")
    session = make(a, Opener())
    a.queue.put_nowait(None)
    await session.close()
    assert [e async for e in session.events()] == []
    assert a.closed


async def test_concurrent_failures_recover_once() -> None:
    a, b = FakeInner("a"), FakeInner("b")
    opener = Opener(b, FakeInner("unused"))
    session = make(a, opener)
    a.dead = True
    stream = session.events()
    b.queue.put_nowait(TranscriptEvent("partial", "y"))
    await asyncio.gather(session.send_audio(b"1"), anext(stream))
    assert len(opener.excluded_seen) == 1
    await stream.aclose()


async def test_failed_replay_tries_next_instance_and_excludes_it() -> None:
    a, bad, good = FakeInner("a"), FakeInner("bad", replay_fails=True), FakeInner("good")
    opener = Opener(bad, good)
    session = make(a, opener, max_failovers=3)
    await session.send_audio(b"1")
    a.dead = True
    await session.send_audio(b"2")
    assert good.sent == [b"1", b"2"]
    assert bad.failed and bad.closed
    assert opener.excluded_seen[1] == {"a", "bad"}


async def test_failover_budget_exhausted() -> None:
    a = FakeInner("a", dead=True)
    session = make(a, Opener(FakeInner("b", dead=True)), max_failovers=1)
    with pytest.raises(TranscriberUnavailableError, match="budget"):
        await session.send_audio(b"1")


async def test_no_instance_left_propagates() -> None:
    session = make(FakeInner("a", dead=True), Opener())
    with pytest.raises(TranscriberUnavailableError, match="no instance"):
        await session.send_audio(b"1")


async def test_zero_failovers_disables_recovery() -> None:
    session = make(FakeInner("a", dead=True), Opener(FakeInner("b")), max_failovers=0)
    with pytest.raises(TranscriberUnavailableError):
        await session.send_audio(b"1")


async def test_stale_recovery_request_is_ignored() -> None:
    a, b = FakeInner("a"), FakeInner("b")
    opener = Opener(b, FakeInner("unused"))
    session = make(a, opener)
    a.dead = True
    await session.send_audio(b"1")
    await session._recover(0)
    assert len(opener.excluded_seen) == 1


class RecordingObserver:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def recovering(self) -> None:
        self.calls.append(("recovering",))

    async def resumed(self, instance: str, failovers: int) -> None:
        self.calls.append(("resumed", instance, failovers))

    async def finished(self, status: object) -> None:
        self.calls.append(("finished", status))


async def test_observer_sees_failover_and_end() -> None:
    a, b = FakeInner("a"), FakeInner("b")
    observer = RecordingObserver()
    session = ResilientSession(Opener(b), a, observer=observer)
    a.dead = True
    await session.send_audio(b"1")
    await session.close()
    assert observer.calls == [
        ("recovering",),
        ("resumed", "b", 1),
        ("finished", StreamStatus.ENDED),
    ]


async def test_observer_told_when_failover_budget_exhausted() -> None:
    observer = RecordingObserver()
    session = ResilientSession(
        Opener(FakeInner("b", dead=True)),
        FakeInner("a", dead=True),
        max_failovers=1,
        observer=observer,
    )
    with pytest.raises(TranscriberUnavailableError):
        await session.send_audio(b"1")
    assert observer.calls[-1] == ("finished", StreamStatus.FAILED)


async def test_observer_told_when_no_instance_left() -> None:
    observer = RecordingObserver()
    session = ResilientSession(Opener(), FakeInner("a", dead=True), observer=observer)
    with pytest.raises(TranscriberUnavailableError):
        await session.send_audio(b"1")
    assert observer.calls == [("recovering",), ("finished", StreamStatus.FAILED)]

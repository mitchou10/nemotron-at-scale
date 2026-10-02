"""Vosk client tests against a fake server speaking the vosk-server protocol."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest
from websockets.asyncio.server import ServerConnection, serve

from app.services.gateway import Gateway
from app.services.transcription import TranscriberUnavailableError, TranscriptEvent
from app.services.vosk import ENDPOINT_KEEP_MS, EOF, VoskTranscriber
from tests.discovery_helpers import discovery_for
from tests.test_gateway import fake_instance, running, url


@dataclass
class FakeVosk:
    port: int = 0
    replies: list[dict[str, object]] = field(default_factory=list)
    final_text: str = ""
    die_after: int | None = None
    close_after: int | None = None
    reply_delay: float = 0.0
    received: list[bytes] = field(default_factory=list)
    configs: list[dict[str, object]] = field(default_factory=list)
    eofs: int = 0
    connections: int = 0


@asynccontextmanager
async def fake_vosk(**kw: object) -> AsyncIterator[FakeVosk]:
    fake = FakeVosk(**kw)  # type: ignore[arg-type]

    async def handler(ws: ServerConnection) -> None:
        fake.connections += 1
        async for message in ws:
            if isinstance(message, str):
                if "config" in message:
                    fake.configs.append(json.loads(message)["config"])
                elif message == EOF:
                    fake.eofs += 1
                    await ws.send(json.dumps({"text": fake.final_text}))
                    return
                continue
            fake.received.append(message)
            if fake.die_after is not None and len(fake.received) >= fake.die_after:
                ws.transport.abort()
                return
            reply = fake.replies.pop(0) if fake.replies else {"partial": ""}
            await asyncio.sleep(fake.reply_delay)
            await ws.send(json.dumps(reply))
            if fake.close_after is not None and len(fake.received) >= fake.close_after:
                await ws.close()
                return

    async with serve(handler, "127.0.0.1", 0) as server:
        fake.port = next(iter(server.sockets)).getsockname()[1]
        yield fake


def vosk_url(port: int) -> str:
    return f"ws://127.0.0.1:{port}"


async def collect(session: object, count: int) -> list[TranscriptEvent]:
    events: list[TranscriptEvent] = []
    async for event in session.events():  # type: ignore[attr-defined]
        events.append(event)
        if len(events) == count:
            break
    return events


async def test_config_announces_16khz_sample_rate() -> None:
    async with fake_vosk() as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.send_audio(b"\x00\x00")
        await session.close()
    assert vosk.configs == [{"sample_rate": 16000}]
    assert vosk.received == [b"\x00\x00"]


async def test_partials_skip_empty_and_repeated_text() -> None:
    replies = [{"partial": "hel"}, {"partial": "hel"}, {"partial": ""}, {"partial": "hello"}]
    async with fake_vosk(replies=replies) as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        for _ in replies:
            await session.send_audio(b"\x00\x00")
        events = await collect(session, 2)
        await session.close()
    assert events == [TranscriptEvent("partial", "hel"), TranscriptEvent("partial", "hello")]


async def test_utterance_closed_by_the_server_gives_final_then_trim() -> None:
    async with fake_vosk(replies=[{"partial": "hello"}, {"text": "hello world"}]) as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.send_audio(b"\x00\x00")
        await session.send_audio(b"\x00\x00")
        events = await collect(session, 3)
        await session.close()
    assert events == [
        TranscriptEvent("partial", "hello"),
        TranscriptEvent("final", "hello world"),
        TranscriptEvent("trim", "", keep_ms=ENDPOINT_KEEP_MS),
    ]


async def test_empty_utterance_only_trims() -> None:
    async with fake_vosk(replies=[{"text": ""}]) as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.send_audio(b"\x00\x00")
        [event] = await collect(session, 1)
        await session.close()
    assert event.type == "trim"


async def test_end_flushes_the_utterance_with_eof_and_commits() -> None:
    async with fake_vosk(replies=[{"partial": "hi"}], final_text="hi there") as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.send_audio(b"\x00\x00")
        await session.end()
        events = await collect(session, 3)
        await session.close()
    assert events == [
        TranscriptEvent("partial", "hi"),
        TranscriptEvent("final", "hi there"),
        TranscriptEvent("committed", ""),
    ]
    assert vosk.eofs == 1


async def test_end_with_nothing_said_only_commits() -> None:
    async with fake_vosk(final_text="") as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.end()
        [event] = await collect(session, 1)
        await session.close()
    assert event == TranscriptEvent("committed", "")


async def test_stream_reconnects_after_an_end() -> None:
    async with fake_vosk(replies=[{"partial": "a"}, {"partial": "b"}], final_text="a") as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.send_audio(b"\x00\x00")
        await session.end()
        await session.send_audio(b"\x01\x00")
        events = await collect(session, 4)
        await session.close()
    assert [e.type for e in events] == ["partial", "final", "committed", "partial"]
    assert events[-1].text == "b"
    assert vosk.connections == 2
    assert vosk.configs == [{"sample_rate": 16000}] * 2
    assert vosk.received == [b"\x00\x00", b"\x01\x00"]


async def test_two_ends_in_a_row_commit_in_order() -> None:
    async with fake_vosk(final_text="x") as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.send_audio(b"\x00\x00")
        await session.end()
        await session.end()
        events = await collect(session, 3)
        await session.close()
    assert [e.type for e in events] == ["final", "committed", "committed"]


async def test_clean_close_without_eof_is_reported_as_lost() -> None:
    async with fake_vosk(close_after=1) as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.send_audio(b"\x00\x00")
        with pytest.raises(TranscriberUnavailableError, match="closed the stream"):
            async for _ in session.events():
                pass
        await session.close()


async def test_close_ends_the_event_stream() -> None:
    async with fake_vosk() as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.close()
        assert [e async for e in session.events()] == []


async def test_reconnect_failure_raises() -> None:
    async with fake_vosk(final_text="x") as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.send_audio(b"\x00\x00")
        await session.end()
    with pytest.raises(TranscriberUnavailableError):
        await session.send_audio(b"\x00\x00")
    await session.close()


async def test_ping() -> None:
    async with fake_vosk() as vosk:
        assert await VoskTranscriber(vosk_url(vosk.port)).ping() is True
    assert await VoskTranscriber("ws://127.0.0.1:1").ping() is False


async def test_unreachable_server_raises() -> None:
    with pytest.raises(TranscriberUnavailableError):
        await VoskTranscriber("ws://127.0.0.1:1").open_session()


async def test_dropped_connection_raises() -> None:
    async with fake_vosk(die_after=1) as vosk:
        session = await VoskTranscriber(vosk_url(vosk.port)).open_session()
        await session.send_audio(b"\x00\x00")
        with pytest.raises(TranscriberUnavailableError):
            async for _ in session.events():
                pass
        with pytest.raises(TranscriberUnavailableError):
            await session.send_audio(b"\x00\x00")
        with pytest.raises(TranscriberUnavailableError):
            await session.end()


def mixed_gateway(nemo_port: int, vosk_port: int, nemo_limit: int = 8) -> Gateway:
    urls = f"{url(nemo_port)}#{nemo_limit},vosk://127.0.0.1:{vosk_port}"
    return Gateway(discovery_for(urls, 8))


async def test_vosk_instance_is_discovered_probed_and_reported() -> None:
    async with fake_instance("n") as nemo, fake_vosk() as vosk:
        gw = mixed_gateway(nemo.port, vosk.port)
        async with running(gw):
            kinds = {s["instance"]: (s["kind"], s["healthy"]) for s in gw.status()}
    assert kinds == {
        f"127.0.0.1:{nemo.port}": ("nemo", True),
        f"127.0.0.1:{vosk.port}": ("vosk", True),
    }


async def test_down_vosk_instance_is_unhealthy() -> None:
    gw = Gateway(discovery_for("vosk://127.0.0.1:1", 8))
    async with running(gw):
        [entry] = gw.status()
    assert (entry["kind"], entry["healthy"]) == ("vosk", False)


async def test_streams_overflow_from_nemo_to_vosk() -> None:
    async with fake_instance("n") as nemo, fake_vosk(replies=[{"partial": "from vosk"}]) as vosk:
        gw = mixed_gateway(nemo.port, vosk.port, nemo_limit=1)
        async with running(gw):
            first = await gw.open_session("a")
            second = await gw.open_session("b")
            await second.send_audio(b"\x00\x00")
            [event] = await collect(second, 1)
            await first.close()
            await second.close()
    assert event == TranscriptEvent("partial", "from vosk")


async def test_stream_fails_over_from_nemo_to_vosk_and_replays_audio() -> None:
    chunks = [b"\x01\x00", b"\x02\x00"]
    async with (
        fake_instance("n", die_after=2) as nemo,
        fake_vosk(
            replies=[{"partial": "one"}, {"partial": "one two"}, {"partial": "one two three"}]
        ) as vosk,
    ):
        gw = mixed_gateway(nemo.port, vosk.port)
        async with running(gw):
            session = await gw.open_session("alice")
            for chunk in chunks:
                await session.send_audio(chunk)
            texts: list[str] = []
            async for event in session.events():
                texts.append(event.text)
                if event.text == "one two":
                    break
            await session.close()
    assert vosk.received == chunks
    assert texts[-1] == "one two"


async def test_latency_is_reported_for_every_audio_chunk_but_not_for_eof() -> None:
    latencies: list[float] = []
    async with fake_vosk(reply_delay=0.05, final_text="x") as vosk:
        session = await VoskTranscriber(
            vosk_url(vosk.port), on_latency=latencies.append
        ).open_session()
        for _ in range(3):
            await session.send_audio(b"\x00\x00")
        await session.end()
        await collect(session, 2)
        await session.close()
    assert len(latencies) == 3
    assert all(0.05 <= latency < 1.0 for latency in latencies)


async def test_gateway_publishes_vosk_chunk_latency_per_instance() -> None:
    async with fake_vosk(reply_delay=0.02) as vosk:
        gw = Gateway(discovery_for(f"vosk://127.0.0.1:{vosk.port}", 8))
        async with running(gw):
            labels = {"instance": f"127.0.0.1:{vosk.port}"}
            session = await gw.open_session("alice")

            async def drain() -> None:
                async for _ in session.events():
                    pass

            reader = asyncio.create_task(drain())
            for _ in range(4):
                await session.send_audio(b"\x00\x00")
            await asyncio.sleep(0.3)
            registry = gw.metrics.registry
            count = registry.get_sample_value("asr_chunk_latency_seconds_count", labels)
            total = registry.get_sample_value("asr_chunk_latency_seconds_sum", labels)
            reader.cancel()
            await session.close()
    assert count == 4
    assert total is not None and total >= 4 * 0.02

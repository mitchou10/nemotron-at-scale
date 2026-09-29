"""Gateway tests against fake nemo-speech instances (HTTP /ready + realtime WebSocket)."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http import HTTPStatus

import pytest
from websockets.asyncio.server import Request, ServerConnection, serve
from websockets.http11 import Response

from app.services import discovery as discovery_module
from app.services import gateway as gateway_module
from app.services.discovery import DiscoveredInstance, Discovery, DnsDiscovery, parse_endpoints
from app.services.gateway import Gateway
from app.services.state import (
    InMemoryStateStore,
    InstanceState,
    InstanceStatus,
    StreamState,
    StreamStatus,
)
from app.services.transcription import (
    TranscriberBusyError,
    TranscriberUnavailableError,
    TranscriptEvent,
)

PATH = "/v1/audio/transcriptions/realtime"


@dataclass
class FakeInstance:
    name: str
    ready_delay: float = 0.0
    ready_status: int = 200
    port: int = 0
    die_after: int | None = None
    received: list[bytes] = field(default_factory=list)


async def _ws_handler(instance: FakeInstance, ws: ServerConnection) -> None:
    async for message in ws:
        if isinstance(message, bytes):
            instance.received.append(message)
            if instance.die_after is not None and len(instance.received) >= instance.die_after:
                ws.transport.abort()
                return
            await ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.input_audio_transcription.delta",
                        "delta": instance.name,
                    }
                )
            )


@asynccontextmanager
async def fake_instance(
    name: str, host: str = "127.0.0.1", **kw: float | int
) -> AsyncIterator[FakeInstance]:
    instance = FakeInstance(name, **kw)  # type: ignore[arg-type]

    async def handler(ws: ServerConnection) -> None:
        await _ws_handler(instance, ws)

    async def process_request(connection: ServerConnection, request: Request) -> Response | None:
        if request.path == "/ready":
            await asyncio.sleep(instance.ready_delay)
            return connection.respond(HTTPStatus(instance.ready_status), "{}\n")
        return None

    async with serve(handler, host, 0, process_request=process_request) as server:
        instance.port = next(iter(server.sockets)).getsockname()[1]
        yield instance


def make_gateway(urls: list[str], max_streams: int = 8, **kw: float) -> Gateway:
    endpoints = parse_endpoints(",".join(urls), max_streams)
    return Gateway(DnsDiscovery(endpoints), **kw)  # type: ignore[arg-type]


def url(port: int, host: str = "127.0.0.1") -> str:
    return f"ws://{host}:{port}{PATH}"


@asynccontextmanager
async def running(gw: Gateway) -> AsyncIterator[Gateway]:
    await gw.start()
    try:
        yield gw
    finally:
        await gw.stop()


async def stream_name(gw: Gateway) -> tuple[str, object]:
    session = await gw.open_session()
    await session.send_audio(b"\x00\x00")
    async for event in session.events():
        assert isinstance(event, TranscriptEvent)
        return event.text, session
    raise AssertionError("no event")


async def open_n(gw: Gateway, n: int) -> tuple[list[str], list[object]]:
    names, sessions = [], []
    for _ in range(n):
        name, session = await stream_name(gw)
        names.append(name)
        sessions.append(session)
    return names, sessions


async def close_all(sessions: list[object]) -> None:
    for session in sessions:
        await session.close()  # type: ignore[attr-defined]


async def test_fills_first_instance_before_next() -> None:
    async with fake_instance("a") as a, fake_instance("b") as b:
        gw = make_gateway([url(a.port), url(b.port)], max_streams=2)
        async with running(gw):
            names, sessions = await open_n(gw, 3)
            await close_all(sessions)
    assert names == ["a", "a", "b"]


async def test_per_url_limit_overrides_default() -> None:
    async with fake_instance("a") as a, fake_instance("b") as b:
        gw = make_gateway([url(a.port) + "#1", url(b.port) + "#3"], max_streams=8)
        async with running(gw):
            names, sessions = await open_n(gw, 4)
            limits = {s["instance"]: s["max_streams"] for s in gw.status()}
            await close_all(sessions)
    assert names == ["a", "b", "b", "b"]
    assert limits == {f"127.0.0.1:{a.port}": 1, f"127.0.0.1:{b.port}": 3}


async def test_freed_slot_is_reused_before_next_instance() -> None:
    async with fake_instance("a") as a, fake_instance("b") as b:
        gw = make_gateway([url(a.port), url(b.port)], max_streams=1)
        async with running(gw):
            first, s1 = await stream_name(gw)
            second, s2 = await stream_name(gw)
            await s1.close()  # type: ignore[attr-defined]
            third, s3 = await stream_name(gw)
            await close_all([s2, s3])
    assert [first, second, third] == ["a", "b", "a"]


async def test_replicas_of_same_url_fill_in_address_order(monkeypatch: pytest.MonkeyPatch) -> None:
    async with fake_instance("a", host="0.0.0.0") as a:

        async def fake_resolve(host: str, port: int) -> list[str]:
            return ["127.0.0.2", "127.0.0.1"]

        monkeypatch.setattr(discovery_module, "resolve_ipv4", fake_resolve)
        gw = make_gateway([url(a.port, "svc")], max_streams=1)
        async with running(gw):
            s1 = await gw.open_session()
            after_first = {s["instance"]: s["active_streams"] for s in gw.status()}
            s2 = await gw.open_session()
            after_second = {s["instance"]: s["active_streams"] for s in gw.status()}
            await close_all([s1, s2])
    assert after_first == {f"127.0.0.1:{a.port}": 1, f"127.0.0.2:{a.port}": 0}
    assert after_second == {f"127.0.0.1:{a.port}": 1, f"127.0.0.2:{a.port}": 1}


async def test_slow_instance_used_only_as_last_resort() -> None:
    async with fake_instance("slow", ready_delay=0.15) as slow, fake_instance("fast") as fast:
        gw = make_gateway([url(slow.port), url(fast.port)], max_streams=1, max_latency_ms=50)
        async with running(gw):
            names, sessions = await open_n(gw, 2)
            await close_all(sessions)
    assert names == ["fast", "slow"]


async def test_latency_threshold_ignored_when_zero() -> None:
    async with fake_instance("slow", ready_delay=0.1) as slow, fake_instance("fast") as fast:
        gw = make_gateway([url(slow.port), url(fast.port)])
        async with running(gw):
            name, session = await stream_name(gw)
            await session.close()  # type: ignore[attr-defined]
    assert name == "slow"


async def test_status_reports_latency_and_active_streams() -> None:
    async with fake_instance("a") as a:
        gw = make_gateway([url(a.port)], max_streams=3)
        async with running(gw):
            session = await gw.open_session()
            [entry] = gw.status()
            await session.close()
            after = gw.status()[0]
    assert entry["healthy"] is True
    assert entry["active_streams"] == 1
    assert entry["max_streams"] == 3
    assert isinstance(entry["latency_ms"], float)
    assert after["active_streams"] == 0


async def test_busy_when_all_instances_at_capacity() -> None:
    async with fake_instance("a") as a:
        gw = make_gateway([url(a.port)], max_streams=1)
        async with running(gw):
            session = await gw.open_session()
            with pytest.raises(TranscriberBusyError):
                await gw.open_session()
            await session.close()
            await (await gw.open_session()).close()


async def test_unavailable_when_no_instance() -> None:
    gw = make_gateway(["ws://does-not-exist.invalid:8080" + PATH])
    async with running(gw):
        assert gw.status() == []
        with pytest.raises(TranscriberUnavailableError) as exc:
            await gw.open_session()
        assert not isinstance(exc.value, TranscriberBusyError)


async def test_unready_instance_is_skipped() -> None:
    async with fake_instance("down", ready_status=503) as down, fake_instance("up") as up:
        gw = make_gateway([url(down.port), url(up.port)])
        async with running(gw):
            name, session = await stream_name(gw)
            await session.close()  # type: ignore[attr-defined]
            statuses = {s["instance"]: s["healthy"] for s in gw.status()}
    assert name == "up"
    assert statuses[f"127.0.0.1:{down.port}"] is False


async def test_failover_when_connect_fails_despite_healthy_probe() -> None:
    async with fake_instance("good") as good:
        gw = make_gateway([url(good.port)])
        async with running(gw):
            broken = next(iter(gw._instances.values()))
            broken_copy = gateway_module.Instance(
                "127.0.0.1:1",
                -1,
                8,
                url(1),
                "http://127.0.0.1:1/ready",
                broken.transcriber.__class__(url(1)),
            )
            broken_copy.healthy = True
            broken_copy.latency_ms = 0.0
            gw._instances["127.0.0.1:1"] = broken_copy
            name, session = await stream_name(gw)
            await session.close()  # type: ignore[attr-defined]
            assert broken_copy.healthy is False
            assert broken_copy.active == 0
    assert name == "good"


async def test_all_instances_failing_raises() -> None:
    async with fake_instance("a") as a:
        gw = make_gateway([url(a.port)])
        async with running(gw):
            instance = next(iter(gw._instances.values()))
            instance.transcriber = broken_transcriber()  # type: ignore[assignment]
            with pytest.raises(TranscriberUnavailableError):
                await gw.open_session()
            assert instance.active == 0


def broken_transcriber() -> object:
    class Broken:
        async def open_session(self) -> None:
            raise TranscriberUnavailableError("nope")

    return Broken()


async def test_session_failure_marks_instance_unhealthy() -> None:
    async with fake_instance("a") as a:
        gw = make_gateway([url(a.port)])
        async with running(gw):
            session = await gw._open_tracked(set())
            inner = session._inner

            async def boom(*_: object) -> None:
                raise TranscriberUnavailableError("gone")

            async def boom_events() -> AsyncIterator[TranscriptEvent]:
                raise TranscriberUnavailableError("gone")
                yield  # pragma: no cover

            inner.send_audio = boom
            inner.end = boom
            inner.events = boom_events
            instance = next(iter(gw._instances.values()))
            for call in (session.send_audio(b"x"), session.end()):
                instance.healthy = True
                with pytest.raises(TranscriberUnavailableError):
                    await call
                assert instance.healthy is False
            instance.healthy = True
            with pytest.raises(TranscriberUnavailableError):
                async for _ in session.events():
                    pass
            assert instance.healthy is False
            await session.close()
            await session.close()
            assert instance.active == 0


async def test_discovery_removes_vanished_and_drains_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with fake_instance("a") as a:
        addresses = ["127.0.0.1"]

        async def fake_resolve(host: str, port: int) -> list[str]:
            return list(addresses)

        monkeypatch.setattr(discovery_module, "resolve_ipv4", fake_resolve)
        gw = make_gateway([url(a.port, "svc")])
        async with running(gw):
            key = f"127.0.0.1:{a.port}"
            session = await gw.open_session()
            addresses.clear()
            await gw.refresh()
            assert key in gw._instances and gw.status()[0]["healthy"] is False
            with pytest.raises(TranscriberUnavailableError):
                await gw.open_session()
            await session.close()
            await gw.refresh()
            assert gw.status() == []
            addresses.append("127.0.0.1")
            await gw.refresh()
            assert gw.status()[0]["healthy"] is True


async def test_periodic_refresh_runs() -> None:
    async with fake_instance("a") as a:
        gw = make_gateway([url(a.port)], probe_interval=0.01)
        async with running(gw):
            instance = next(iter(gw._instances.values()))
            instance.healthy = False
            await asyncio.sleep(0.15)
            assert instance.healthy is True


async def test_wss_uses_https_probe_url() -> None:
    gw = make_gateway(["wss://127.0.0.1:9443" + PATH])
    await gw._discover()
    [instance] = gw._instances.values()
    assert instance.probe_url == "https://127.0.0.1:9443/ready"
    assert instance.url.startswith("wss://127.0.0.1:9443")


async def test_unreachable_instance_marked_unhealthy() -> None:
    gw = make_gateway([url(1)])
    async with running(gw):
        [entry] = gw.status()
    assert entry["healthy"] is False
    assert entry["latency_ms"] is None


async def test_stream_resumes_on_another_instance_after_crash() -> None:
    chunks = [b"\x01\x00", b"\x02\x00", b"\x03\x00"]
    async with fake_instance("a", die_after=2) as a, fake_instance("b") as b:
        gw = make_gateway([url(a.port), url(b.port)], max_streams=4)
        async with running(gw):
            session = await gw.open_session()
            await session.send_audio(chunks[0])
            await session.send_audio(chunks[1])
            seen: list[str] = []
            async for event in session.events():
                seen.append(event.text)
                if event.text == "bb":
                    break
            await session.send_audio(chunks[2])
            await session.close()
            healthy = {s["instance"]: s["healthy"] for s in gw.status()}
            active = {s["instance"]: s["active_streams"] for s in gw.status()}
    assert seen[0] == "a"
    assert seen[-1] == "bb"
    assert b.received[:2] == chunks[:2]
    assert healthy[f"127.0.0.1:{a.port}"] is False
    assert set(active.values()) == {0}


def state_gateway(urls: list[str], **kw: float) -> tuple[Gateway, InMemoryStateStore]:
    store = InMemoryStateStore()
    gw = Gateway(DnsDiscovery(parse_endpoints(",".join(urls), 4)), store=store, **kw)  # type: ignore[arg-type]
    return gw, store


async def test_state_records_which_client_is_on_which_instance() -> None:
    async with fake_instance("a") as a:
        gw, store = state_gateway([url(a.port)])
        async with running(gw):
            session = await gw.open_session("alice")
            [stream] = await store.list_streams(active_only=True)
            [saved] = await store.list_instances()
            await session.close()
            [after] = await store.list_streams()
            [saved_after] = await store.list_instances()
    key = f"127.0.0.1:{a.port}"
    assert (stream.client_id, stream.instance, stream.status) == (
        "alice",
        key,
        StreamStatus.RUNNING,
    )
    assert (saved.key, saved.status, saved.active_streams) == (key, InstanceStatus.UP, 1)
    assert (after.status, after.ended_at is not None) == (StreamStatus.ENDED, True)
    assert saved_after.active_streams == 0


async def test_state_follows_a_stream_moved_by_failover() -> None:
    async with fake_instance("a", die_after=1) as a, fake_instance("b") as b:
        gw, store = state_gateway([url(a.port), url(b.port)])
        async with running(gw):
            session = await gw.open_session("alice")
            await session.send_audio(b"\x01\x00")
            async for event in session.events():
                if event.text == "b":
                    break
            [stream] = await store.list_streams(active_only=True)
            instances = {i.key: i for i in await store.list_instances()}
            await session.close()
    assert stream.instance == f"127.0.0.1:{b.port}"
    assert stream.failovers == 1
    assert stream.status == StreamStatus.RUNNING
    assert instances[f"127.0.0.1:{b.port}"].active_streams == 1
    assert instances[f"127.0.0.1:{a.port}"].status == InstanceStatus.DOWN


async def test_state_marks_unreachable_instance_down() -> None:
    gw, store = state_gateway([url(1)])
    async with running(gw):
        [saved] = await store.list_instances()
    assert saved.status == InstanceStatus.DOWN


async def test_state_marks_draining_then_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    async with fake_instance("a") as a:
        addresses = ["127.0.0.1"]

        async def fake_resolve(host: str, port: int) -> list[str]:
            return list(addresses)

        monkeypatch.setattr(discovery_module, "resolve_ipv4", fake_resolve)
        gw, store = state_gateway([url(a.port, "svc")])
        async with running(gw):
            session = await gw.open_session("alice")
            addresses.clear()
            await gw.refresh()
            [draining] = await store.list_instances()
            await session.close()
            await gw.refresh()
            [gone] = await store.list_instances()
    assert draining.status == InstanceStatus.DRAINING
    assert gone.status == InstanceStatus.GONE


async def test_start_interrupts_streams_left_by_a_previous_process() -> None:
    gw, store = state_gateway([url(1)])
    await store.save_stream(StreamState("ghost", "1.2.3.4:8080"))
    async with running(gw):
        [stream] = await store.list_streams()
    assert stream.status == StreamStatus.INTERRUPTED


class BrokenStore(InMemoryStateStore):
    async def save_stream(self, state: StreamState) -> None:
        raise RuntimeError("database down")

    async def save_instance(self, state: InstanceState) -> None:
        raise RuntimeError("database down")

    async def interrupt_active_streams(self) -> int:
        raise RuntimeError("database down")


async def test_gateway_keeps_working_when_the_store_is_down() -> None:
    async with fake_instance("a") as a:
        gw = Gateway(
            DnsDiscovery(parse_endpoints(url(a.port), 4)),
            store=BrokenStore(),
        )
        async with running(gw):
            name, session = await stream_name(gw)
            await session.close()  # type: ignore[attr-defined]
    assert name == "a"


async def test_gateway_accepts_any_discovery() -> None:
    class Fixed(Discovery):
        def __init__(self, port: int) -> None:
            self._port = port

        async def discover(self) -> list[DiscoveredInstance]:
            return [
                DiscoveredInstance(
                    key=f"127.0.0.1:{self._port}",
                    url=url(self._port),
                    probe_url=f"http://127.0.0.1:{self._port}/ready",
                    max_streams=1,
                    priority=0,
                )
            ]

    async with fake_instance("a") as a:
        gw = Gateway(Fixed(a.port))
        async with running(gw):
            name, session = await stream_name(gw)
            with pytest.raises(TranscriberBusyError):
                await gw.open_session()
            await session.close()  # type: ignore[attr-defined]
    assert name == "a"

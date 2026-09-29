"""Gateway metrics tests, read back from the Prometheus registry."""

import sys

import pytest
from starlette.testclient import TestClient

from tests.test_gateway import (
    Gateway,
    fake_instance,
    make_gateway,
    running,
    stream_name,
    url,
)


def sample(gw: Gateway, name: str, **labels: str) -> float | None:
    return gw.metrics.registry.get_sample_value(name, labels)


async def test_instance_gauges_are_published() -> None:
    async with fake_instance("a") as a:
        gw = make_gateway([url(a.port)], max_streams=3)
        async with running(gw):
            key = f"127.0.0.1:{a.port}"
            session = await gw.open_session("alice")
            assert sample(gw, "asr_instance_up", instance=key) == 1
            assert sample(gw, "asr_instance_active_streams", instance=key) == 1
            assert sample(gw, "asr_instance_max_streams", instance=key) == 3
            assert (sample(gw, "asr_instance_latency_ms", instance=key) or 0) > 0
            await session.close()
            assert sample(gw, "asr_instance_active_streams", instance=key) == 0


async def test_probe_and_open_latency_histograms() -> None:
    async with fake_instance("a", ready_delay=0.05) as a:
        gw = make_gateway([url(a.port)])
        async with running(gw):
            key = f"127.0.0.1:{a.port}"
            session = await gw.open_session()
            await session.close()
            assert sample(gw, "asr_instance_probe_seconds_count", instance=key) == 1
            assert (sample(gw, "asr_instance_probe_seconds_sum", instance=key) or 0) >= 0.05
            assert sample(gw, "asr_session_open_seconds_count", instance=key) == 1
            assert sample(gw, "asr_streams_opened_total", instance=key) == 1


async def test_first_result_latency_is_observed_once() -> None:
    async with fake_instance("a") as a:
        gw = make_gateway([url(a.port)])
        async with running(gw):
            key = f"127.0.0.1:{a.port}"
            session = await gw.open_session()
            await session.send_audio(b"\x00\x00")
            await session.send_audio(b"\x00\x00")
            seen = 0
            async for _ in session.events():
                seen += 1
                if seen == 2:
                    break
            await session.close()
            assert sample(gw, "asr_first_result_seconds_count", instance=key) == 1


async def test_probe_failures_and_down_gauge() -> None:
    gw = make_gateway([url(1)])
    async with running(gw):
        key = "127.0.0.1:1"
        assert sample(gw, "asr_instance_probe_failures_total", instance=key) == 1
        assert sample(gw, "asr_instance_up", instance=key) == 0


async def test_failover_and_failure_counters() -> None:
    async with fake_instance("a", die_after=1) as a, fake_instance("b") as b:
        gw = make_gateway([url(a.port), url(b.port)])
        async with running(gw):
            key_a, key_b = f"127.0.0.1:{a.port}", f"127.0.0.1:{b.port}"
            session = await gw.open_session()
            await session.send_audio(b"\x01\x00")
            async for event in session.events():
                if event.text == "b":
                    break
            await session.close()
            assert sample(gw, "asr_instance_failures_total", instance=key_a) == 1
            assert sample(gw, "asr_failovers_total", instance=key_b) == 1
            assert sample(gw, "asr_failovers_total", instance=key_a) is None


async def test_open_failure_counter() -> None:
    async with fake_instance("a") as a:
        gw = make_gateway([url(a.port)])
        async with running(gw):
            instance = next(iter(gw._instances.values()))

            class Broken:
                async def open_session(self) -> None:
                    from app.services.transcription import TranscriberUnavailableError

                    raise TranscriberUnavailableError("nope")

            instance.transcriber = Broken()  # type: ignore[assignment]
            with pytest.raises(Exception):  # noqa: B017
                await gw.open_session()
            assert sample(gw, "asr_stream_open_failures_total", instance=instance.key) == 1
            assert sample(gw, "asr_streams_rejected_total", reason="unavailable") == 1


async def test_rejection_reasons() -> None:
    async with fake_instance("a") as a:
        gw = make_gateway([url(a.port)], max_streams=1)
        async with running(gw):
            session = await gw.open_session()
            with pytest.raises(Exception):  # noqa: B017
                await gw.open_session()
            await session.close()
            assert sample(gw, "asr_streams_rejected_total", reason="busy") == 1


async def test_vanished_instance_series_are_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import discovery as discovery_module

    async with fake_instance("a") as a:
        addresses = ["127.0.0.1"]

        async def fake_resolve(host: str, port: int) -> list[str]:
            return list(addresses)

        monkeypatch.setattr(discovery_module, "resolve_ipv4", fake_resolve)
        gw = make_gateway([url(a.port, "svc")])
        async with running(gw):
            key = f"127.0.0.1:{a.port}"
            assert sample(gw, "asr_instance_up", instance=key) == 1
            addresses.clear()
            await gw.refresh()
            assert sample(gw, "asr_instance_up", instance=key) is None
            gw.metrics.forget_instance(key)


async def test_metrics_endpoint_serves_gateway_metrics(ws_client: TestClient) -> None:
    async with fake_instance("a") as a:
        gw = make_gateway([url(a.port)])
        async with running(gw):
            name, session = await stream_name(gw)
            await session.close()  # type: ignore[attr-defined]
            ws_client.app.state.transcriber = gw
            response = ws_client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert f'asr_streams_opened_total{{instance="127.0.0.1:{a.port}"}} 1.0' in response.text
    assert name == "a"


def test_metrics_endpoint_empty_when_disabled(ws_client: TestClient) -> None:
    response = ws_client.get("/metrics")
    assert response.status_code == 200
    assert response.text == ""


async def test_buffer_bytes_per_instance_follow_the_stream() -> None:
    async with fake_instance("a", die_after=3) as a, fake_instance("b") as b:
        gw = make_gateway([url(a.port), url(b.port)])
        async with running(gw):
            key_a, key_b = f"127.0.0.1:{a.port}", f"127.0.0.1:{b.port}"
            assert sample(gw, "asr_buffer_bytes", instance=key_a) == 0
            assert sample(gw, "asr_buffer_limit_bytes") == 30 * 32_000

            session = await gw.open_session()
            await session.send_audio(b"\x00" * 100)
            await session.send_audio(b"\x00" * 50)
            assert sample(gw, "asr_buffer_bytes", instance=key_a) == 150
            assert sample(gw, "asr_buffer_bytes", instance=key_b) == 0

            await session.send_audio(b"\x00" * 10)  # instance a dies on this chunk
            async for event in session.events():
                if event.text == "b":
                    break
            assert sample(gw, "asr_buffer_bytes", instance=key_a) == 0
            assert sample(gw, "asr_buffer_bytes", instance=key_b) == 160

            await session.close()
            assert sample(gw, "asr_buffer_bytes", instance=key_b) == 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="process metrics are Linux-only")
def test_backend_process_memory_is_exposed() -> None:
    gw = make_gateway([url(1)])
    assert (sample(gw, "process_resident_memory_bytes") or 0) > 0

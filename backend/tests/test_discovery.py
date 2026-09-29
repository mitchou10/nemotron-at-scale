"""Discovery tests."""

import pytest

from app.services import discovery as discovery_module
from app.services.discovery import (
    DiscoveredInstance,
    Discovery,
    DnsDiscovery,
    Endpoint,
    StaticDiscovery,
    parse_endpoints,
    resolve_ipv4,
)

PATH = "/v1/audio/transcriptions/realtime"


def test_discovery_is_abstract() -> None:
    with pytest.raises(TypeError):
        Discovery()  # type: ignore[abstract]


async def test_static_discovery_one_instance_per_endpoint_in_order() -> None:
    discovery = StaticDiscovery(
        [Endpoint(f"ws://gpu:8080{PATH}", 16), Endpoint(f"wss://cpu.example{PATH}", 4)]
    )
    assert await discovery.discover() == [
        DiscoveredInstance("gpu:8080", f"ws://gpu:8080{PATH}", "http://gpu:8080/ready", 16, 0),
        DiscoveredInstance(
            "cpu.example:443",
            f"wss://cpu.example:443{PATH}",
            "https://cpu.example:443/ready",
            4,
            1,
        ),
    ]


async def test_static_discovery_defaults_port_to_80() -> None:
    [instance] = await StaticDiscovery([Endpoint(f"ws://asr{PATH}", 1)]).discover()
    assert instance.key == "asr:80"


async def test_dns_discovery_expands_hostname_to_each_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return {"gpu": ["10.0.0.2", "10.0.0.1"], "cpu": []}[host]

    monkeypatch.setattr(discovery_module, "resolve_ipv4", fake_resolve)
    found = await DnsDiscovery(
        [Endpoint(f"ws://gpu:8080{PATH}", 16), Endpoint(f"ws://cpu:8080{PATH}", 4)]
    ).discover()
    assert [(d.key, d.priority, d.max_streams) for d in found] == [
        ("10.0.0.2:8080", 0, 16),
        ("10.0.0.1:8080", 0, 16),
    ]
    assert found[0].url == f"ws://10.0.0.2:8080{PATH}"
    assert found[0].probe_url == "http://10.0.0.2:8080/ready"


async def test_resolve_ipv4() -> None:
    assert await resolve_ipv4("127.0.0.1", 80) == ["127.0.0.1"]
    assert await resolve_ipv4("does-not-exist.invalid", 80) == []


def test_parse_endpoints() -> None:
    assert parse_endpoints(f"ws://a:1{PATH}#16, ws://b:2{PATH} ,,", 8) == [
        Endpoint(f"ws://a:1{PATH}", 16),
        Endpoint(f"ws://b:2{PATH}", 8),
    ]
    assert parse_endpoints("", 8) == []


def test_parse_vosk_endpoint_defaults_to_port_2700() -> None:
    assert parse_endpoints("vosk://asr-vosk#4,vosk://other:2800", 8) == [
        Endpoint("ws://asr-vosk:2700", 4, "vosk"),
        Endpoint("ws://other:2800", 8, "vosk"),
    ]


async def test_vosk_instances_are_probed_on_their_own_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["10.0.0.7"]

    monkeypatch.setattr(discovery_module, "resolve_ipv4", fake_resolve)
    [found] = await DnsDiscovery(parse_endpoints("vosk://asr-vosk", 8)).discover()
    assert (found.kind, found.key, found.url, found.probe_url) == (
        "vosk",
        "10.0.0.7:2700",
        "ws://10.0.0.7:2700",
        "ws://10.0.0.7:2700",
    )
    [static] = await StaticDiscovery(parse_endpoints("vosk://asr-vosk", 8)).discover()
    assert static.kind == "vosk"

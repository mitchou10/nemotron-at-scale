"""Discovery tests."""

from datetime import timedelta

import pytest

from app.services.discovery import (
    DiscoveredInstance,
    Discovery,
    RegistryDiscovery,
    describe_instance,
)
from app.services.registry import InMemoryRegistryStore, RegisteredInstance
from app.services.state import utcnow

PATH = "/v1/audio/transcriptions/realtime"


def test_discovery_is_abstract() -> None:
    with pytest.raises(TypeError):
        Discovery()  # type: ignore[abstract]


def test_describe_nemo_instance_is_probed_over_http() -> None:
    assert describe_instance("nemo", f"ws://10.0.0.5:8080{PATH}", 16, 2) == DiscoveredInstance(
        key="10.0.0.5:8080",
        url=f"ws://10.0.0.5:8080{PATH}",
        probe_url="http://10.0.0.5:8080/ready",
        max_streams=16,
        priority=2,
        kind="nemo",
    )


def test_describe_secure_instance_and_default_ports() -> None:
    secure = describe_instance("nemo", f"wss://asr{PATH}", 4)
    assert (secure.key, secure.probe_url) == ("asr:443", "https://asr:443/ready")
    plain = describe_instance("nemo", f"ws://asr{PATH}", 4)
    assert plain.key == "asr:80"


def test_describe_vosk_instance_is_probed_with_its_own_url() -> None:
    vosk = describe_instance("vosk", f"ws://asr-vosk:8080{PATH}", 12)
    assert vosk.kind == "vosk"
    assert vosk.probe_url == vosk.url == f"ws://asr-vosk:8080{PATH}"


def test_describe_drops_the_fragment() -> None:
    assert describe_instance("nemo", f"ws://a:1{PATH}#16", 4).url == f"ws://a:1{PATH}"


async def test_registry_discovery_returns_alive_asr_instances_in_fill_order() -> None:
    registry = InMemoryRegistryStore()
    await registry.upsert(RegisteredInstance("b", "vosk", f"ws://b:8080{PATH}", 12, priority=1))
    await registry.upsert(RegisteredInstance("a", "nemo", f"ws://a:8080{PATH}", 16, priority=0))
    await registry.upsert(RegisteredInstance("t", "tts", "http://t:8080", 4))
    stale = RegisteredInstance("old", "nemo", f"ws://old:8080{PATH}", 4)
    stale.last_seen = utcnow() - timedelta(seconds=60)
    await registry.upsert(stale)

    found = await RegistryDiscovery(registry, ttl_s=30).discover()

    assert [(d.key, d.kind, d.max_streams, d.priority) for d in found] == [
        ("a:8080", "nemo", 16, 0),
        ("b:8080", "vosk", 12, 1),
    ]


async def test_an_instance_that_unregisters_disappears() -> None:
    registry = InMemoryRegistryStore()
    await registry.upsert(RegisteredInstance("a", "nemo", f"ws://a:8080{PATH}", 4))
    discovery = RegistryDiscovery(registry, ttl_s=30)
    assert len(await discovery.discover()) == 1
    await registry.remove("a")
    assert await discovery.discover() == []

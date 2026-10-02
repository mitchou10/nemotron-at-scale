"""Discovery of the transcription instances the gateway can route streams to.

Instances register themselves (see `registry.py`): there is no DNS or static list any more.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from app.services.registry import RegisteredInstance, RegistryStore

AsrKind = Literal["nemo", "vosk"]
ASR_KINDS: tuple[AsrKind, ...] = ("nemo", "vosk")


@dataclass(frozen=True)
class DiscoveredInstance:
    key: str
    url: str
    probe_url: str
    max_streams: int
    priority: int
    kind: AsrKind = "nemo"


class Discovery(ABC):
    """Tells the gateway which instances exist right now.

    `priority` is the fill order: lower is filled first.
    """

    @abstractmethod
    async def discover(self) -> list[DiscoveredInstance]: ...


def describe_instance(
    kind: AsrKind, url: str, max_streams: int, priority: int = 0
) -> DiscoveredInstance:
    """Build the gateway's view of an instance from the realtime WebSocket URL it announced."""
    parts = urlsplit(url)
    secure = parts.scheme == "wss"
    port = parts.port or (443 if secure else 80)
    key = f"{parts.hostname or ''}:{port}"
    url = parts._replace(netloc=key, fragment="").geturl()
    # Vosk has no HTTP health route: it is probed with a WebSocket handshake on its own URL.
    probe_url = url if kind == "vosk" else f"{'https' if secure else 'http'}://{key}/ready"
    return DiscoveredInstance(key, url, probe_url, max_streams, priority, kind)


class RegistryDiscovery(Discovery):
    """The instances that registered and whose heartbeat is recent."""

    def __init__(self, registry: RegistryStore, ttl_s: float) -> None:
        self._registry = registry
        self._ttl_s = ttl_s

    async def discover(self) -> list[DiscoveredInstance]:
        alive = await self._registry.list_alive(self._ttl_s, kinds=ASR_KINDS)
        return [self._describe(i) for i in alive]

    @staticmethod
    def _describe(instance: RegisteredInstance) -> DiscoveredInstance:
        kind: AsrKind = "vosk" if instance.kind == "vosk" else "nemo"
        return describe_instance(kind, instance.url, instance.max_streams, instance.priority)

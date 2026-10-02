"""Registry of the worker instances: they register, send heartbeats, and disappear when they stop.

An instance (a transcription server or a text-to-speech server) calls the registry routes with the
address it announces for itself. It is alive as long as its last heartbeat is younger than the TTL;
a clean shutdown unregisters it at once.
"""

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from app.services.state import utcnow

InstanceKind = Literal["nemo", "vosk", "tts"]
KINDS: tuple[InstanceKind, ...] = ("nemo", "vosk", "tts")


@dataclass
class RegisteredInstance:
    id: str
    kind: str
    url: str
    max_streams: int
    priority: int = 0
    registered_at: datetime = field(default_factory=utcnow)
    last_seen: datetime = field(default_factory=utcnow)


class RegistryStore(ABC):
    @abstractmethod
    async def upsert(self, instance: RegisteredInstance) -> None:
        """Register `instance`, or refresh its heartbeat (and fields) if it is already known."""

    @abstractmethod
    async def remove(self, instance_id: str) -> bool:
        """Unregister; False if it was not registered."""

    @abstractmethod
    async def list_alive(
        self, ttl_s: float, kinds: Sequence[str] | None = None
    ) -> list[RegisteredInstance]:
        """Instances whose last heartbeat is younger than `ttl_s`, by priority then id."""

    @abstractmethod
    async def prune(self, ttl_s: float) -> int:
        """Delete the instances that missed their heartbeats; return how many."""


def sort_key(instance: RegisteredInstance) -> tuple[int, str]:
    return (instance.priority, instance.id)


class InMemoryRegistryStore(RegistryStore):
    def __init__(self) -> None:
        self._instances: dict[str, RegisteredInstance] = {}

    async def upsert(self, instance: RegisteredInstance) -> None:
        known = self._instances.get(instance.id)
        if known:
            instance = dataclasses.replace(instance, registered_at=known.registered_at)
        self._instances[instance.id] = dataclasses.replace(instance)

    async def remove(self, instance_id: str) -> bool:
        return self._instances.pop(instance_id, None) is not None

    async def list_alive(
        self, ttl_s: float, kinds: Sequence[str] | None = None
    ) -> list[RegisteredInstance]:
        limit = utcnow() - timedelta(seconds=ttl_s)
        alive = [
            dataclasses.replace(i)
            for i in self._instances.values()
            if i.last_seen >= limit and (kinds is None or i.kind in kinds)
        ]
        return sorted(alive, key=sort_key)

    async def prune(self, ttl_s: float) -> int:
        limit = utcnow() - timedelta(seconds=ttl_s)
        stale = [k for k, i in self._instances.items() if i.last_seen < limit]
        for key in stale:
            del self._instances[key]
        return len(stale)

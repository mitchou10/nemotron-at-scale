"""Log of the text-to-speech requests that went through the gateway, for the admin statistics."""

import dataclasses
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from app.services.state import utcnow

MAX_IN_MEMORY = 50_000


@dataclass
class TtsCallRecord:
    status_code: int
    instance: str | None = None
    voice: str | None = None
    response_format: str | None = None
    characters: int = 0
    audio_bytes: int = 0
    duration_ms: int = 0
    first_byte_ms: int | None = None
    at: datetime = field(default_factory=utcnow)
    id: int | None = None


class TtsCallStore(ABC):
    @abstractmethod
    async def add(self, call: TtsCallRecord) -> None: ...

    @abstractmethod
    async def list_since(
        self, since: datetime, *, limit: int | None = None, status_class: str | None = None
    ) -> list[TtsCallRecord]:
        """Calls made at or after `since`, newest first. `status_class`: ok, client_error, error."""

    @abstractmethod
    async def prune(self, before: datetime) -> int:
        """Delete the calls older than `before`; return how many."""


def matches_status(status_code: int, status_class: str | None) -> bool:
    if status_class is None:
        return True
    if status_class == "ok":
        return status_code < 400
    if status_class == "client_error":
        return 400 <= status_code < 500
    return status_code >= 500


class InMemoryTtsCallStore(TtsCallStore):
    def __init__(self) -> None:
        self._calls: deque[TtsCallRecord] = deque(maxlen=MAX_IN_MEMORY)
        self._next_id = 1

    async def add(self, call: TtsCallRecord) -> None:
        self._calls.append(dataclasses.replace(call, id=self._next_id))
        self._next_id += 1

    async def list_since(
        self, since: datetime, *, limit: int | None = None, status_class: str | None = None
    ) -> list[TtsCallRecord]:
        found = [
            dataclasses.replace(c)
            for c in reversed(self._calls)
            if c.at >= since and matches_status(c.status_code, status_class)
        ]
        return found[:limit] if limit else found

    async def prune(self, before: datetime) -> int:
        kept = deque((c for c in self._calls if c.at >= before), maxlen=MAX_IN_MEMORY)
        removed = len(self._calls) - len(kept)
        self._calls = kept
        return removed

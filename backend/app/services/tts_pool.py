"""Gateway to the text-to-speech instances that registered themselves.

A request goes to the instance with the lowest load (requests in flight over its limit). An instance
that cannot be reached is left out for a few seconds; one that answers 429 (full) or 503 (not ready)
is skipped for this request only, and the next one is tried.
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from starlette.background import BackgroundTask

from app.services.registry import RegisteredInstance, RegistryStore

COOLDOWN_S = 10.0
# Answers that mean "try another instance"; any other one (a 4xx for a bad request...) is final.
RETRY_STATUSES = (429, 502, 503, 504)


@dataclass
class Upstream:
    """An answer to relay to the client, and what to do once it has been sent."""

    status_code: int
    headers: httpx.Headers
    chunks: AsyncIterator[bytes]
    cleanup: BackgroundTask
    instance_id: str | None = None


class NoInstanceError(Exception):
    """No text-to-speech instance is registered, or none could be reached."""

    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class TtsPool:
    def __init__(
        self,
        registry: RegistryStore,
        ttl_s: float,
        *,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._registry = registry
        self._ttl_s = ttl_s
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5.0))
        self._in_flight: dict[str, int] = {}
        self._unreachable_until: dict[str, float] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def instances(self) -> list[RegisteredInstance]:
        """Alive instances, least loaded first. Those that failed recently come last."""
        alive = await self._registry.list_alive(self._ttl_s, kinds=("tts",))
        now = time.monotonic()

        def load(i: RegisteredInstance) -> tuple[bool, float, int, str]:
            cooling = self._unreachable_until.get(i.id, 0.0) > now
            return (cooling, self._in_flight.get(i.id, 0) / max(i.max_streams, 1), i.priority, i.id)

        return sorted(alive, key=load)

    def load(self) -> dict[str, int]:
        return dict(self._in_flight)

    async def post(self, path: str, body: bytes, content_type: str) -> Upstream:
        return await self._send("POST", path, body, content_type)

    async def get(self, path: str) -> Upstream:
        return await self._send("GET", path, None, None)

    async def _send(
        self, method: str, path: str, body: bytes | None, content_type: str | None
    ) -> Upstream:
        candidates = await self.instances()
        if not candidates:
            raise NoInstanceError("no text-to-speech instance is registered")
        headers = dict(self._headers)
        if content_type:
            headers["Content-Type"] = content_type

        last: Upstream | None = None
        for instance in candidates:
            self._in_flight[instance.id] = self._in_flight.get(instance.id, 0) + 1
            try:
                request = self._client.build_request(
                    method, instance.url.rstrip("/") + path, content=body, headers=headers
                )
                response = await self._client.send(request, stream=True)
            except httpx.HTTPError:
                self._release(instance.id)
                self._unreachable_until[instance.id] = time.monotonic() + COOLDOWN_S
                continue
            upstream = Upstream(
                response.status_code,
                response.headers,
                response.aiter_bytes(),
                BackgroundTask(self._finish, response, instance.id),
                instance.id,
            )
            if response.status_code in RETRY_STATUSES:
                if last is not None:
                    await last.cleanup()
                last = upstream
                continue
            if last is not None:
                await last.cleanup()
            return upstream

        if last is not None:  # every instance was busy or not ready: say so to the client
            return last
        raise NoInstanceError("no text-to-speech instance could be reached", 502)

    async def _finish(self, response: httpx.Response, instance_id: str) -> None:
        await response.aclose()
        self._release(instance_id)

    def _release(self, instance_id: str) -> None:
        self._in_flight[instance_id] = max(0, self._in_flight.get(instance_id, 0) - 1)

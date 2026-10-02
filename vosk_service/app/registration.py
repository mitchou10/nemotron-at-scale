"""Registration of this server in the backend's registry.

Once the model is loaded, the server tells the backend where to reach it, then repeats it every
few seconds (the heartbeat). On a clean shutdown it unregisters; if it dies, the backend forgets it
when the heartbeats stop (the TTL). Nothing here can stop the server: a failed call is logged and
retried.
"""

import asyncio
import json
import logging
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import quote, urlsplit

from app.config import Settings

logger = logging.getLogger(__name__)

REALTIME_PATH = "/v1/audio/transcriptions/realtime"


def announced_base_url(settings: Settings) -> str:
    """The address the backend should use: `VOSK_SELF_URL`, or this container's own IP."""
    if settings.self_url:
        return settings.self_url.rstrip("/")
    try:
        host = socket.gethostbyname(socket.gethostname())
    except OSError:
        host = "127.0.0.1"
    return f"http://{host}:{settings.port}"


def realtime_url(base_url: str) -> str:
    """`http://host:8080` -> `ws://host:8080/v1/audio/transcriptions/realtime`."""
    parts = urlsplit(base_url)
    scheme = "wss" if parts.scheme in ("https", "wss") else "ws"
    return parts._replace(scheme=scheme, path=REALTIME_PATH, query="", fragment="").geturl()


class Registration:
    def __init__(
        self,
        settings: Settings,
        is_ready: Callable[[], bool],
        *,
        timeout_s: float = 3.0,
    ) -> None:
        assert settings.registry_url
        self._endpoint = (
            settings.registry_url.rstrip("/")
            + "/api/v1/registry/instances/"
            + quote(settings.registry_id or socket.gethostname(), safe="")
        )
        self._token = settings.registry_token
        self._interval_s = settings.registry_interval_s
        self._body = json.dumps(
            {
                "kind": "vosk",
                "url": realtime_url(announced_base_url(settings)),
                "max_streams": settings.max_streams,
                "priority": settings.registry_priority,
            }
        ).encode()
        self._is_ready = is_ready
        self._timeout_s = timeout_s
        self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered

    async def run(self) -> None:
        """Heartbeat until cancelled. Nothing is sent while the model is not loaded."""
        while True:
            if self._is_ready():
                await self._send_heartbeat()
            await asyncio.sleep(self._interval_s)

    async def close(self) -> None:
        """Unregister (best effort): the backend stops routing to this server at once."""
        if not self._registered:
            return
        try:
            await asyncio.to_thread(self._call, "DELETE", None)
            logger.info("unregistered from the backend")
        except (OSError, urllib.error.URLError) as exc:
            logger.warning("could not unregister (the TTL will do it): %s", exc)
        self._registered = False

    async def _send_heartbeat(self) -> None:
        try:
            await asyncio.to_thread(self._call, "PUT", self._body)
        except (OSError, urllib.error.URLError) as exc:
            if self._registered:
                logger.warning("registration lost: %s", exc)
            self._registered = False
            return
        if not self._registered:
            logger.info("registered in the backend: %s", self._endpoint)
        self._registered = True

    def _call(self, method: str, body: bytes | None) -> None:
        request = urllib.request.Request(  # noqa: S310
            self._endpoint, data=body, method=method
        )
        request.add_header("Content-Type", "application/json")
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        with urllib.request.urlopen(request, timeout=self._timeout_s):  # noqa: S310
            pass

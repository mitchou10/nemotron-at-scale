"""Discovery of the transcription instances the gateway can route streams to."""

import asyncio
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

VOSK_PORT = 2700


@dataclass(frozen=True)
class Endpoint:
    """A configured realtime WebSocket URL and the number of streams one instance may hold."""

    url: str
    max_streams: int
    kind: Literal["nemo", "vosk"] = "nemo"


@dataclass(frozen=True)
class DiscoveredInstance:
    key: str
    url: str
    probe_url: str
    max_streams: int
    priority: int
    kind: Literal["nemo", "vosk"] = "nemo"


class Discovery(ABC):
    """Tells the gateway which instances exist right now.

    `priority` is the fill order: lower is filled first.
    """

    @abstractmethod
    async def discover(self) -> list[DiscoveredInstance]: ...


def _describe(endpoint: Endpoint, priority: int, host: str, port: int) -> DiscoveredInstance:
    parts = urlsplit(endpoint.url)
    secure = parts.scheme == "wss"
    key = f"{host}:{port}"
    url = parts._replace(netloc=key, fragment="").geturl()
    # Vosk has no HTTP health route: it is probed with a WebSocket handshake on its own URL.
    probe_url = url if endpoint.kind == "vosk" else f"{'https' if secure else 'http'}://{key}/ready"
    return DiscoveredInstance(
        key=key,
        url=url,
        probe_url=probe_url,
        max_streams=endpoint.max_streams,
        priority=priority,
        kind=endpoint.kind,
    )


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


def _port(url: str) -> int:
    parts = urlsplit(url)
    return parts.port or (443 if parts.scheme == "wss" else 80)


class StaticDiscovery(Discovery):
    """One instance per configured endpoint, taken as is."""

    def __init__(self, endpoints: list[Endpoint]) -> None:
        self._endpoints = endpoints

    async def discover(self) -> list[DiscoveredInstance]:
        return [
            _describe(
                endpoint, priority, urlsplit(endpoint.url).hostname or "", _port(endpoint.url)
            )
            for priority, endpoint in enumerate(self._endpoints)
        ]


async def resolve_ipv4(host: str, port: int) -> list[str]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=socket.AF_INET, type=socket.SOCK_STREAM
        )
    except OSError:
        return []
    return list(dict.fromkeys(info[4][0] for info in infos))


class DnsDiscovery(Discovery):
    """Resolves each endpoint hostname to all its IPv4 addresses, one instance per address.

    A Docker service scaled with `--scale` resolves to one IP per replica.
    """

    def __init__(self, endpoints: list[Endpoint]) -> None:
        self._endpoints = endpoints

    async def discover(self) -> list[DiscoveredInstance]:
        found: list[DiscoveredInstance] = []
        for priority, endpoint in enumerate(self._endpoints):
            port = _port(endpoint.url)
            hostname = _host(endpoint.url)
            found.extend(
                _describe(endpoint, priority, ip, port) for ip in await resolve_ipv4(hostname, port)
            )
        return found


def parse_endpoints(urls: str, default_max_streams: int) -> list[Endpoint]:
    """Parse `url[#limit],url[#limit],...` (comma separated, in fill order).

    `ws://` / `wss://` URLs are nemo-speech instances; `vosk://host[:2700]` is a Vosk server.
    """
    endpoints = []
    for raw in (u.strip() for u in urls.split(",")):
        if not raw:
            continue
        parts = urlsplit(raw)
        limit = int(parts.fragment) if parts.fragment else default_max_streams
        kind: Literal["nemo", "vosk"] = "nemo"
        if parts.scheme == "vosk":
            kind = "vosk"
            parts = parts._replace(
                scheme="ws", netloc=f"{parts.hostname}:{parts.port or VOSK_PORT}"
            )
        endpoints.append(Endpoint(parts._replace(fragment="").geturl(), limit, kind))
    return endpoints

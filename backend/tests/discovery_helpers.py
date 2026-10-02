"""Test doubles for discovery: a mutable list of instances, built from the old URL syntax."""

from typing import Literal
from urllib.parse import urlsplit

from app.services.discovery import DiscoveredInstance, Discovery, describe_instance


class ListDiscovery(Discovery):
    """The instances in `items`, which a test can change between two refreshes."""

    def __init__(self, items: list[DiscoveredInstance]) -> None:
        self.items = items

    async def discover(self) -> list[DiscoveredInstance]:
        return list(self.items)


def discovery_for(urls: str, default_max_streams: int = 8) -> ListDiscovery:
    """`url[#limit],url[#limit],...` in fill order; `vosk://host:port` is a Vosk server."""
    items: list[DiscoveredInstance] = []
    for priority, raw in enumerate(u.strip() for u in urls.split(",") if u.strip()):
        parts = urlsplit(raw)
        limit = int(parts.fragment) if parts.fragment else default_max_streams
        kind: Literal["nemo", "vosk"] = "nemo"
        if parts.scheme == "vosk":
            kind = "vosk"
            parts = parts._replace(scheme="ws", netloc=f"{parts.hostname}:{parts.port or 2700}")
        items.append(describe_instance(kind, parts._replace(fragment="").geturl(), limit, priority))
    return ListDiscovery(items)

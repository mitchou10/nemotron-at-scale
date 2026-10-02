"""Registration in the backend's registry: heartbeat, unregistration, failures."""

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.registration import Registration, announced_base_url, realtime_url
from tests.conftest import FakeEngine


class Registry:
    """A tiny HTTP server that records what the instance sends."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def _record(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                registry.calls.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "auth": self.headers.get("Authorization"),
                        "body": body,
                    }
                )
                self.send_response(204 if self.command == "DELETE" else 200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_PUT = do_DELETE = _record  # noqa: N815

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def methods(self) -> list[str]:
        return [c["method"] for c in self.calls]


@pytest.fixture
def registry() -> Iterator[Registry]:
    server = Registry()
    yield server
    server.server.shutdown()


def settings_for(registry: Registry, **extra: object) -> Settings:
    return Settings(
        registry_url=registry.url,
        registry_token="tok",
        registry_id="vosk-1",
        registry_interval_s=0.05,
        registry_priority=2,
        self_url="http://asr-vosk:8080",
        max_streams=12,
        **extra,  # type: ignore[arg-type]
    )


def test_urls() -> None:
    assert realtime_url("http://asr:8080") == "ws://asr:8080/v1/audio/transcriptions/realtime"
    assert realtime_url("https://asr") == "wss://asr/v1/audio/transcriptions/realtime"
    assert announced_base_url(Settings(self_url="http://asr:8080/")) == "http://asr:8080"
    assert announced_base_url(Settings(port=9000)).endswith(":9000")


async def test_registers_with_a_heartbeat_then_unregisters(registry: Registry) -> None:
    registration = Registration(settings_for(registry), lambda: True)
    task = asyncio.create_task(registration.run())
    await asyncio.sleep(0.3)
    task.cancel()
    await registration.close()

    assert registry.methods().count("PUT") >= 3  # registered, then heartbeats
    assert registry.methods()[-1] == "DELETE"
    first = registry.calls[0]
    assert first["path"] == "/api/v1/registry/instances/vosk-1"
    assert first["auth"] == "Bearer tok"
    assert first["body"] == {
        "kind": "vosk",
        "url": "ws://asr-vosk:8080/v1/audio/transcriptions/realtime",
        "max_streams": 12,
        "priority": 2,
    }
    assert registration.registered is False


async def test_nothing_is_sent_while_the_model_is_loading(registry: Registry) -> None:
    ready = False
    registration = Registration(settings_for(registry), lambda: ready)
    task = asyncio.create_task(registration.run())
    await asyncio.sleep(0.2)
    assert registry.calls == []
    ready = True
    await asyncio.sleep(0.2)
    task.cancel()
    assert registry.methods()[0] == "PUT"
    await registration.close()


async def test_an_unreachable_registry_never_raises_and_the_server_recovers(
    registry: Registry,
) -> None:
    settings = settings_for(registry)
    settings.registry_url = "http://127.0.0.1:1"  # nobody there
    registration = Registration(settings, lambda: True)
    task = asyncio.create_task(registration.run())
    await asyncio.sleep(0.2)
    assert registration.registered is False
    assert not task.done()
    await registration.close()  # nothing to unregister: no error either
    task.cancel()


def test_lifespan_registers_and_unregisters(registry: Registry) -> None:
    app = create_app(settings_for(registry), engine=FakeEngine(), load_model=False)
    with TestClient(app):
        deadline = time.monotonic() + 3
        while "PUT" not in registry.methods():
            assert time.monotonic() < deadline, "never registered"
            time.sleep(0.02)
    assert registry.methods()[-1] == "DELETE"


def test_no_registration_without_a_registry_url(registry: Registry) -> None:
    app = create_app(Settings(), engine=FakeEngine(), load_model=False)
    with TestClient(app):
        time.sleep(0.1)
    assert registry.calls == []

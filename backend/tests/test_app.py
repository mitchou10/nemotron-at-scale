"""Application factory, lifespan and settings tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient

from app import db
from app.config import Settings, get_settings, settings
from app.main import app, build_gateway, create_app
from app.services.discovery import DnsDiscovery, StaticDiscovery
from app.services.gateway import Gateway
from app.services.state import (
    InMemoryStateStore,
    InstanceState,
    InstanceStatus,
    StreamState,
    StreamStatus,
)
from app.services.state_sql import SqlStateStore


def test_lifespan_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    dispose = AsyncMock()
    monkeypatch.setattr(db, "engine", MagicMock(dispose=dispose))
    with TestClient(app):
        dispose.assert_not_awaited()
    dispose.assert_awaited_once()


async def test_openapi_and_docs_available(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/openapi.json")).status_code == 200
    assert (await client.get("/api/v1/docs")).status_code == 200


async def test_users_routes_absent(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/users/")).status_code == 404


async def test_cors_preflight_allowed_origin(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_create_app_returns_new_instance() -> None:
    assert create_app() is not app


def test_settings_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.APP_PORT == 8000
    assert s.APP_ENV == "development"


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PORT", "9001")
    assert Settings(_env_file=None).APP_PORT == 9001


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_gateway_disabled_by_default() -> None:
    assert build_gateway() is None


def test_gateway_built_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ASR_ENABLED", True)
    assert isinstance(build_gateway(), Gateway)


def test_lifespan_starts_and_stops_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = MagicMock(start=AsyncMock(), stop=AsyncMock(), status=lambda: [{"instance": "x"}])
    monkeypatch.setattr("app.main.build_gateway", lambda: gateway)
    with TestClient(app) as client:
        gateway.start.assert_awaited_once()
        assert client.get("/api/v1/asr/instances").json() == [{"instance": "x"}]
    gateway.stop.assert_awaited_once()


def test_asr_instances_empty_when_disabled(ws_client: TestClient) -> None:
    assert ws_client.get("/api/v1/asr/instances").json() == []


def test_asr_state_routes_empty_when_disabled(ws_client: TestClient) -> None:
    assert ws_client.get("/api/v1/asr/state/instances").json() == []
    assert ws_client.get("/api/v1/asr/state/streams").json() == []


def test_asr_state_routes_return_saved_state(ws_client: TestClient) -> None:
    store = InMemoryStateStore()
    gateway = Gateway(StaticDiscovery([]), store=store)
    ws_client.app.state.transcriber = gateway
    asyncio.run(store.save_instance(InstanceState("a:1", "ws://a:1", InstanceStatus.UP, 0, 8)))
    asyncio.run(store.save_stream(StreamState("alice", "a:1")))
    asyncio.run(store.save_stream(StreamState("bob", "a:1", StreamStatus.ENDED)))

    [instance] = ws_client.get("/api/v1/asr/state/instances").json()
    assert (instance["key"], instance["status"]) == ("a:1", "up")
    assert len(ws_client.get("/api/v1/asr/state/streams").json()) == 2
    [active] = ws_client.get("/api/v1/asr/state/streams?active=true").json()
    assert (active["client_id"], active["instance"], active["status"]) == (
        "alice",
        "a:1",
        "running",
    )


@pytest.mark.parametrize(
    ("discovery", "store", "expected_discovery", "expected_store"),
    [
        ("dns", "database", DnsDiscovery, SqlStateStore),
        ("static", "memory", StaticDiscovery, InMemoryStateStore),
    ],
)
def test_gateway_wiring_follows_settings(
    monkeypatch: pytest.MonkeyPatch,
    discovery: str,
    store: str,
    expected_discovery: type,
    expected_store: type,
) -> None:
    monkeypatch.setattr(settings, "ASR_ENABLED", True)
    monkeypatch.setattr(settings, "ASR_DISCOVERY", discovery)
    monkeypatch.setattr(settings, "ASR_STATE_STORE", store)
    gateway = build_gateway()
    assert gateway is not None
    assert isinstance(gateway._discovery, expected_discovery)
    assert isinstance(gateway.store, expected_store)

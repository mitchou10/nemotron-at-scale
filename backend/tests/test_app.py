"""Application factory, lifespan and settings tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient

from app import db
from app.config import Settings, get_settings
from app.main import app, create_app


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

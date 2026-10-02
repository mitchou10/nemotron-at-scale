"""Pytest fixtures."""

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from app.api.routes.audio import active_clients
from app.main import app
from app.services.registry import InMemoryRegistryStore


@pytest.fixture(autouse=True)
def registry() -> InMemoryRegistryStore:
    """A fresh registry for every test (the app would otherwise use the database)."""
    app.state.registry = InMemoryRegistryStore()
    app.state.tts_pool = None
    return app.state.registry  # type: ignore[no-any-return]


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client bound to the ASGI app."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def ws_client() -> Iterator[TestClient]:
    """Sync client (runs lifespan) used for WebSocket tests."""
    active_clients.clear()
    with TestClient(app) as tc:
        yield tc
    active_clients.clear()

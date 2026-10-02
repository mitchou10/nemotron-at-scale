"""FastAPI application factory."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    asr_router,
    audio_router,
    health_router,
    metrics_router,
    registry_router,
    tts_router,
)
from app.config import settings
from app.db import AsyncSessionLocal
from app.services.discovery import RegistryDiscovery
from app.services.gateway import Gateway
from app.services.registry import InMemoryRegistryStore, RegistryStore
from app.services.registry_sql import SqlRegistryStore
from app.services.state import InMemoryStateStore, StateStore, safely
from app.services.state_sql import SqlStateStore
from app.services.tts_pool import TtsPool

PRUNE_INTERVAL_S = 60.0


async def _prune_registry(registry: RegistryStore) -> None:
    """Forget the instances that have been silent for much longer than the TTL."""
    while True:
        await asyncio.sleep(PRUNE_INTERVAL_S)
        await safely(registry.prune(settings.REGISTRY_TTL_S * 10), "prune the registry")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown events."""
    registry: RegistryStore = app.state.registry
    gateway = build_gateway(registry)
    app.state.transcriber = gateway
    if gateway:
        await gateway.start()
    pool = TtsPool(
        registry,
        settings.REGISTRY_TTL_S,
        api_key=settings.TTS_API_KEY,
        timeout_s=settings.TTS_TIMEOUT_S,
    )
    app.state.tts_pool = pool
    pruner = asyncio.create_task(_prune_registry(registry))
    yield
    pruner.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await pruner
    await pool.close()
    if gateway:
        await gateway.stop()
    await engine_dispose()


def build_registry() -> RegistryStore:
    """The registry of worker instances, shared by every backend replica through the database."""
    if settings.REGISTRY_STORE == "database":
        return SqlRegistryStore(AsyncSessionLocal)
    return InMemoryRegistryStore()


def build_gateway(registry: RegistryStore) -> Gateway | None:
    """Return the ASR gateway when live transcription is enabled."""
    if not settings.ASR_ENABLED:
        return None
    store: StateStore = (
        SqlStateStore(AsyncSessionLocal)
        if settings.ASR_STATE_STORE == "database"
        else InMemoryStateStore()
    )
    return Gateway(
        RegistryDiscovery(registry, settings.REGISTRY_TTL_S),
        settings.ASR_API_KEY,
        store=store,
        probe_interval=settings.ASR_PROBE_INTERVAL_S,
        max_latency_ms=settings.ASR_MAX_LATENCY_MS,
        buffer_seconds=settings.ASR_BUFFER_SECONDS,
        max_failovers=settings.ASR_MAX_FAILOVERS,
        history_interval=settings.ASR_HISTORY_INTERVAL_S,
        history_retention=timedelta(hours=settings.ASR_HISTORY_RETENTION_HOURS),
    )


async def engine_dispose() -> None:
    """Dispose the async engine on shutdown."""
    from app.db import engine

    await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.APP_DEBUG,
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(o) for o in settings.CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.registry = build_registry()

    # Routers
    api_prefix = "/api/v1"
    app.include_router(health_router, prefix=api_prefix)
    app.include_router(audio_router, prefix=api_prefix)
    app.include_router(asr_router, prefix=api_prefix)
    app.include_router(tts_router, prefix=api_prefix)
    app.include_router(registry_router, prefix=api_prefix)
    app.include_router(metrics_router)

    return app


app = create_app()

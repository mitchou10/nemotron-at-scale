"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import asr_router, audio_router, health_router, metrics_router, tts_router
from app.config import settings
from app.db import AsyncSessionLocal
from app.services.discovery import (
    Discovery,
    DnsDiscovery,
    StaticDiscovery,
    parse_endpoints,
)
from app.services.gateway import Gateway
from app.services.state import InMemoryStateStore, StateStore
from app.services.state_sql import SqlStateStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown events."""
    gateway = build_gateway()
    app.state.transcriber = gateway
    if gateway:
        await gateway.start()
    tts = build_tts_client()
    app.state.tts = tts
    yield
    if tts:
        await tts.aclose()
    if gateway:
        await gateway.stop()
    await engine_dispose()


def build_tts_client() -> httpx.AsyncClient | None:
    """Return the HTTP client of the text-to-speech service when it is enabled."""
    if not settings.TTS_ENABLED:
        return None
    headers = {"Authorization": f"Bearer {settings.TTS_API_KEY}"} if settings.TTS_API_KEY else {}
    return httpx.AsyncClient(
        base_url=settings.TTS_URL,
        headers=headers,
        timeout=httpx.Timeout(settings.TTS_TIMEOUT_S, connect=5.0),
    )


def build_gateway() -> Gateway | None:
    """Return the ASR gateway when live transcription is enabled."""
    if not settings.ASR_ENABLED:
        return None
    endpoints = parse_endpoints(settings.ASR_URL, settings.ASR_MAX_STREAMS_PER_INSTANCE)
    discovery: Discovery = (
        DnsDiscovery(endpoints) if settings.ASR_DISCOVERY == "dns" else StaticDiscovery(endpoints)
    )
    store: StateStore = (
        SqlStateStore(AsyncSessionLocal)
        if settings.ASR_STATE_STORE == "database"
        else InMemoryStateStore()
    )
    return Gateway(
        discovery,
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

    # Routers
    api_prefix = "/api/v1"
    app.include_router(health_router, prefix=api_prefix)
    app.include_router(audio_router, prefix=api_prefix)
    app.include_router(asr_router, prefix=api_prefix)
    app.include_router(tts_router, prefix=api_prefix)
    app.include_router(metrics_router)

    return app


app = create_app()

"""Routes package."""

from app.api.routes.audio import router as audio_router
from app.api.routes.health import router as health_router

__all__ = ["audio_router", "health_router"]

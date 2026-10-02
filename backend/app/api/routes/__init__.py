"""Routes package."""

from app.api.routes.asr import router as asr_router
from app.api.routes.audio import router as audio_router
from app.api.routes.health import router as health_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.tts import router as tts_router

__all__ = ["asr_router", "audio_router", "health_router", "metrics_router", "tts_router"]

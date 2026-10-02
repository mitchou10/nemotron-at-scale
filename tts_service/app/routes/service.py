"""Service routes: /, /health, /ready, /live, /version, /v1/models, /v1/audio/voices, /metrics."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import __version__
from app.auth import require_api_key
from app.errors import error_body

router = APIRouter()

PLAYGROUND = (Path(__file__).parent.parent / "static" / "playground.html").read_text("utf-8")
# Names accepted in `model`: all of them use the same Piper voices.
MODEL_IDS = ("tts-1", "tts-1-hd")


@router.get("/", include_in_schema=False)
async def playground() -> HTMLResponse:
    """Small web page to type a text and hear it."""
    return HTMLResponse(PLAYGROUND)


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    state = request.app.state.server
    body = {"status": "ok" if state.ready else "error", "version": __version__}
    return JSONResponse(body, status_code=200 if state.ready else 503)


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    state = request.app.state.server
    if not state.ready:
        detail = state.load_error or "the voices are loading"
        return JSONResponse({"ready": False, "detail": detail}, status_code=503)
    return JSONResponse(
        {
            "ready": True,
            "device": "cpu",
            "capabilities": ["tts"],
            "engine": state.engine.name,
            "voices": [v.id for v in state.engine.voices],
            "active_requests": state.active_requests,
            "max_requests": state.settings.max_requests,
        }
    )


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness: the process answers, whether or not the voices are loaded."""
    return {"status": "alive"}


@router.get("/ready/capacity")
async def ready_capacity(request: Request) -> JSONResponse:
    """Readiness for load balancing: 503 while loading or when the instance is full."""
    state = request.app.state.server
    body: dict[str, object] = {
        "ready": state.ready and not state.at_capacity,
        "active_requests": state.active_requests,
        "max_requests": state.settings.max_requests,
    }
    if not state.ready:
        body["detail"] = state.load_error or "the voices are loading"
    elif state.at_capacity:
        body["detail"] = "at capacity"
    return JSONResponse(body, status_code=200 if body["ready"] else 503)


@router.get("/version")
async def version() -> dict[str, str]:
    return {"version": __version__}


@router.get("/v1/models", dependencies=[Depends(require_api_key)])
async def models(request: Request) -> JSONResponse:
    state = request.app.state.server
    if not state.ready:
        return JSONResponse(error_body("the voices are not loaded", "server_error"), 503)
    data = [{"id": m, "object": "model", "owned_by": "piper"} for m in MODEL_IDS]
    return JSONResponse({"object": "list", "data": data})


@router.get("/v1/audio/voices", dependencies=[Depends(require_api_key)])
async def voices(request: Request) -> JSONResponse:
    """Installed voices (an extension: OpenAI has no such route)."""
    state = request.app.state.server
    if not state.ready:
        return JSONResponse(error_body("the voices are not loaded", "server_error"), 503)
    data = [
        {"id": v.id, "language": v.language, "sample_rate": v.sample_rate}
        for v in state.engine.voices
    ]
    return JSONResponse({"object": "list", "data": data})


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    registry = request.app.state.server.metrics.registry
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

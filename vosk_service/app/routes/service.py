"""Service routes: /, /health, /ready, /version, /v1/models, /metrics."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import __version__
from app.auth import require_api_key
from app.errors import error_body

router = APIRouter()

PLAYGROUND = (Path(__file__).parent.parent / "static" / "playground.html").read_text("utf-8")


@router.get("/", include_in_schema=False)
async def playground() -> HTMLResponse:
    """Small web page to try a WAV upload or the microphone."""
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
        detail = state.load_error or "the model is loading"
        return JSONResponse({"ready": False, "detail": detail}, status_code=503)
    return JSONResponse(
        {
            "ready": True,
            "device": "cpu",
            "capabilities": ["asr"],
            "model": state.engine.name,
            "language": state.engine.language,
            "active_streams": state.active_streams,
            "max_streams": state.settings.max_streams,
        }
    )


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness: the process answers, whether or not the model is loaded."""
    return {"status": "alive"}


@router.get("/ready/capacity")
async def ready_capacity(request: Request) -> JSONResponse:
    """Readiness for load balancing: 503 while loading or when the instance is full."""
    state = request.app.state.server
    body: dict[str, object] = {
        "ready": state.ready and not state.at_capacity,
        "active_streams": state.active_streams,
        "max_streams": state.settings.max_streams,
    }
    if not state.ready:
        body["detail"] = state.load_error or "the model is loading"
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
        return JSONResponse(error_body("the model is not loaded", "server_error"), status_code=503)
    engine = state.engine
    entry = {
        "id": engine.name,
        "object": "model",
        "owned_by": "vosk",
        "capabilities": ["asr"],
        "language": engine.language,
    }
    return JSONResponse({"object": "list", "data": [entry]})


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    registry = request.app.state.server.metrics.registry
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

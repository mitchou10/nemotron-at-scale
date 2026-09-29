"""ASR gateway status routes."""

from fastapi import APIRouter, Request

from app.services.state import InstanceState, StreamState

router = APIRouter(tags=["asr"])


@router.get("/asr/instances")
async def asr_instances(request: Request) -> list[dict[str, object]]:
    """Live latency, load and health of each transcription instance."""
    gateway = request.app.state.transcriber
    return gateway.status() if gateway else []


@router.get("/asr/state/instances")
async def saved_instances(request: Request) -> list[InstanceState]:
    """Last saved state of each instance (up, down, draining, gone)."""
    gateway = request.app.state.transcriber
    return await gateway.store.list_instances() if gateway else []


@router.get("/asr/state/streams")
async def saved_streams(request: Request, active: bool = False) -> list[StreamState]:
    """Saved streams: which client is on which instance, and whether it is still running."""
    gateway = request.app.state.transcriber
    return await gateway.store.list_streams(active_only=active) if gateway else []

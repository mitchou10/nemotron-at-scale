"""ASR gateway status routes."""

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.services.history import summarize
from app.services.state import InstanceState, StreamState, utcnow

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


@router.get("/asr/history")
async def asr_history(
    request: Request,
    hours: Annotated[float, Query(gt=0, le=720)] = 24,
    buckets: Annotated[int, Query(ge=1, le=240)] = 90,
) -> dict[str, Any]:
    """Uptime, latency and load of each instance over the last `hours`, in `buckets` time slices."""
    until = utcnow()
    since = until - timedelta(hours=hours)
    gateway = request.app.state.transcriber
    samples = await gateway.store.list_samples(since) if gateway else []
    streams = await gateway.store.list_streams(since=since) if gateway else []
    return summarize(samples, streams, since=since, until=until, buckets=buckets)

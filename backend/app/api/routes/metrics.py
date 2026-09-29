"""Prometheus scrape endpoint."""

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Gateway metrics (empty when live transcription is disabled)."""
    gateway = request.app.state.transcriber
    body = generate_latest(gateway.metrics.registry) if gateway else b""
    return Response(body, media_type=CONTENT_TYPE_LATEST)

"""Admin routes: statistics, workers, recent calls. Protected by ADMIN_TOKEN."""

import secrets
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.config import settings
from app.services import stats
from app.services.calls import TtsCallStore
from app.services.discovery import describe_instance
from app.services.registry import RegistryStore
from app.services.state import ACTIVE_STREAM_STATUSES, StreamStatus, utcnow
from app.services.tts_pool import TtsPool


async def require_admin_token(request: Request) -> None:
    """With ADMIN_TOKEN set, only holders of the token may read the statistics."""
    expected = settings.ADMIN_TOKEN
    if not expected:
        return
    header = request.headers.get("authorization", "")
    provided = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not secrets.compare_digest(expected, provided):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing admin token")


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)])

Hours = Annotated[float, Query(gt=0, le=24 * 90)]


def _calls(request: Request) -> TtsCallStore | None:
    return getattr(request.app.state, "tts_calls", None)


async def _workers(request: Request) -> list[dict[str, Any]]:
    """Registered instances, with what the gateway knows of the transcription ones."""
    registry: RegistryStore = request.app.state.registry
    gateway = getattr(request.app.state, "transcriber", None)
    pool: TtsPool | None = getattr(request.app.state, "tts_pool", None)
    live = {s["instance"]: s for s in gateway.status()} if gateway else {}
    in_flight = pool.load() if pool else {}
    now = utcnow()

    workers = []
    for item in await registry.list_alive(settings.REGISTRY_TTL_S):
        row: dict[str, Any] = {
            "id": item.id,
            "kind": item.kind,
            "url": item.url,
            "priority": item.priority,
            "max_streams": item.max_streams,
            "registered_at": item.registered_at.isoformat(),
            "last_seen": item.last_seen.isoformat(),
            "age_s": round((now - item.last_seen).total_seconds(), 1),
            "healthy": True,
            "latency_ms": None,
            "active": 0,
        }
        if item.kind == "tts":
            row["active"] = in_flight.get(item.id, 0)
        else:
            kind = "vosk" if item.kind == "vosk" else "nemo"
            seen = live.get(describe_instance(kind, item.url, item.max_streams).key)
            if seen:
                row.update(
                    healthy=bool(seen["healthy"]),
                    latency_ms=seen["latency_ms"],
                    active=seen["active_streams"],
                )
            else:  # registered, but the gateway has not probed it yet (or ASR is disabled)
                row["healthy"] = False
        workers.append(row)
    return workers


@router.get("/overview")
async def overview(request: Request, hours: Hours = 24) -> dict[str, Any]:
    """Headline numbers over the last `hours`: calls, errors, latency, load, workers."""
    until = utcnow()
    since = until - timedelta(hours=hours)
    gateway = getattr(request.app.state, "transcriber", None)
    streams = await gateway.store.list_streams(since=since) if gateway else []
    active = len(await gateway.store.list_streams(active_only=True)) if gateway else 0
    calls_store = _calls(request)
    calls = await calls_store.list_since(since) if calls_store else []

    workers = await _workers(request)
    by_kind: dict[str, dict[str, int]] = {}
    for w in workers:
        counts = by_kind.setdefault(w["kind"], {"total": 0, "healthy": 0})
        counts["total"] += 1
        counts["healthy"] += bool(w["healthy"])

    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "hours": hours,
        "stt": stats.stt_summary(streams, active_now=active),
        "tts": stats.tts_summary(calls),
        "workers": {
            "total": len(workers),
            "healthy": sum(bool(w["healthy"]) for w in workers),
            "by_kind": by_kind,
            "asr_enabled": gateway is not None,
        },
    }


@router.get("/timeseries")
async def timeseries(
    request: Request, hours: Hours = 24, buckets: Annotated[int, Query(ge=1, le=240)] = 48
) -> dict[str, Any]:
    """Streams started and TTS requests per time slice."""
    until = utcnow()
    since = until - timedelta(hours=hours)
    gateway = getattr(request.app.state, "transcriber", None)
    streams = await gateway.store.list_streams(since=since) if gateway else []
    calls_store = _calls(request)
    calls = await calls_store.list_since(since) if calls_store else []
    return stats.timeseries(streams, calls, since=since, until=until, buckets=buckets)


@router.get("/workers")
async def workers(request: Request) -> list[dict[str, Any]]:
    """Every registered worker: health, latency and load."""
    return await _workers(request)


@router.get("/stt/streams")
async def stt_streams(
    request: Request,
    hours: Hours = 24,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    state: str | None = None,
) -> list[dict[str, Any]]:
    """Recent audio streams, newest first. `state`: active, ended, failed or interrupted."""
    gateway = getattr(request.app.state, "transcriber", None)
    if not gateway:
        return []
    wanted = {"active": [str(s) for s in ACTIVE_STREAM_STATUSES]}.get(state or "")
    if state and state != "active" and state not in {str(s) for s in StreamStatus}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown state")
    found = await gateway.store.list_streams(since=utcnow() - timedelta(hours=hours))
    rows = []
    for s in reversed(found):
        if state and str(s.status) not in (wanted or [state]):
            continue
        rows.append(
            {
                "id": s.id,
                "client_id": s.client_id,
                "instance": s.instance,
                "status": str(s.status),
                "failovers": s.failovers,
                "started_at": s.started_at.isoformat(),
                "duration_s": round(stats.stream_duration_s(s), 1),
            }
        )
        if len(rows) >= limit:
            break
    return rows


@router.get("/tts/calls")
async def tts_calls(
    request: Request,
    hours: Hours = 24,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    result: Annotated[str | None, Query(pattern="^(ok|client_error|error)$")] = None,
) -> list[dict[str, Any]]:
    """Recent text-to-speech requests, newest first. `result`: ok, client_error or error."""
    store = _calls(request)
    if not store:
        return []
    found = await store.list_since(
        utcnow() - timedelta(hours=hours), limit=limit, status_class=result
    )
    return [
        {
            "id": c.id,
            "at": c.at.isoformat(),
            "status_code": c.status_code,
            "instance": c.instance,
            "voice": c.voice,
            "format": c.response_format,
            "characters": c.characters,
            "audio_bytes": c.audio_bytes,
            "duration_ms": c.duration_ms,
            "first_byte_ms": c.first_byte_ms,
        }
        for c in found
    ]

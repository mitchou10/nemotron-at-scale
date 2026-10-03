"""Text-to-speech routes: the gateway to the registered `tts_service` instances."""

import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask, BackgroundTasks

from app.services.calls import TtsCallRecord, TtsCallStore
from app.services.state import safely
from app.services.tts_pool import NoInstanceError, TtsPool

router = APIRouter(tags=["tts"])

PASSED_HEADERS = ("x-voice",)


def _error(message: str, status_code: int, error_type: str = "server_error") -> JSONResponse:
    """Same shape as OpenAI and tts_service, so one client handles every error."""
    return JSONResponse({"error": {"message": message, "type": error_type}}, status_code)


def _request_facts(body: bytes) -> tuple[int, str | None]:
    """Length of `input` and `response_format` of a speech request (best effort)."""
    try:
        payload = json.loads(body)
    except ValueError:
        return 0, None
    if not isinstance(payload, dict):
        return 0, None
    text = payload.get("input")
    fmt = payload.get("response_format", "mp3")
    return (len(text) if isinstance(text, str) else 0), (fmt if isinstance(fmt, str) else None)


async def _relay(request: Request, method: str, path: str, body: bytes | None = None) -> Response:
    pool: TtsPool | None = getattr(request.app.state, "tts_pool", None)
    if pool is None:
        return _error("text-to-speech is not available", 503)
    calls: TtsCallStore | None = getattr(request.app.state, "tts_calls", None)
    record = method == "POST" and calls is not None
    characters, response_format = _request_facts(body or b"") if record else (0, None)
    started = time.perf_counter()
    try:
        if method == "POST":
            content_type = request.headers.get("content-type", "application/json")
            upstream = await pool.post(path, body or b"", content_type)
        else:
            upstream = await pool.get(path)
    except NoInstanceError as exc:
        if record and calls:
            call = TtsCallRecord(
                exc.status_code,
                response_format=response_format,
                characters=characters,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            await safely(calls.add(call), "log a text-to-speech call")
        return _error(str(exc), exc.status_code)

    tasks = BackgroundTasks()
    chunks = upstream.chunks
    if record and calls:
        counter = _Counter()
        chunks = _counting(upstream.chunks, counter, started)

        async def log_call() -> None:
            call = TtsCallRecord(
                upstream.status_code,
                instance=upstream.instance_id,
                voice=upstream.headers.get("x-voice"),
                response_format=response_format,
                characters=characters,
                audio_bytes=counter.bytes,
                duration_ms=round((time.perf_counter() - started) * 1000),
                first_byte_ms=counter.first_byte_ms,
            )
            await safely(calls.add(call), "log a text-to-speech call")

        tasks.add_task(upstream.cleanup)
        tasks.add_task(BackgroundTask(log_call))
    else:
        tasks.add_task(upstream.cleanup)

    return StreamingResponse(
        chunks,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers={k: v for k in PASSED_HEADERS if (v := upstream.headers.get(k))},
        background=tasks,
    )


class _Counter:
    def __init__(self) -> None:
        self.bytes = 0
        self.first_byte_ms: int | None = None


async def _counting(
    chunks: AsyncIterator[bytes], counter: _Counter, started: float
) -> AsyncIterator[bytes]:
    async for chunk in chunks:
        if counter.first_byte_ms is None:
            counter.first_byte_ms = round((time.perf_counter() - started) * 1000)
        counter.bytes += len(chunk)
        yield chunk


@router.post("/audio/speech")
async def speech(request: Request) -> Response:
    """OpenAI-compatible `POST /audio/speech`: `{model, input, voice, response_format, speed}`.

    Point an OpenAI client at `<backend>/api/v1` as its base URL. The request goes to the least
    loaded text-to-speech instance; the audio is relayed as it is synthesized (mp3 and pcm), so the
    first sentence can play before the last one is done.
    """
    return await _relay(request, "POST", "/v1/audio/speech", await request.body())


@router.get("/audio/voices")
async def voices(request: Request) -> Response:
    """Voices installed on the text-to-speech instances."""
    return await _relay(request, "GET", "/v1/audio/voices")

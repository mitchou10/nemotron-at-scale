"""POST /v1/audio/transcriptions: OpenAI-compatible speech-to-text on a WAV upload."""

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from app.audio import Audio, parse_wav
from app.auth import require_api_key
from app.engine import Engine
from app.errors import ApiError
from app.formats import RESPONSE_FORMATS, Word, srt, vtt

router = APIRouter()

CHUNK_SECONDS = 0.25


def transcribe(engine: Engine, audio: Audio) -> tuple[str, list[Word]]:
    """Decode a whole file (CPU-bound: call from a worker thread)."""
    recognizer = engine.create_recognizer(audio.sample_rate, True)
    step = int(audio.sample_rate * CHUNK_SECONDS) * 2
    results: list[dict[str, Any]] = []
    for offset in range(0, len(audio.pcm), step):
        if recognizer.accept_waveform(audio.pcm[offset : offset + step]):
            results.append(recognizer.result())
    results.append(recognizer.final_result())

    texts = [str(r["text"]) for r in results if r.get("text")]
    words = [
        Word(w["word"], w["start"], w["end"], w.get("conf", 1.0))
        for r in results
        for w in r.get("result", [])
    ]
    return " ".join(texts), words


@router.post("/v1/audio/transcriptions", dependencies=[Depends(require_api_key)])
async def transcriptions(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    model: str = Form(""),  # accepted for client compatibility: one model is loaded
    language: str = Form(""),
    response_format: str = Form("json"),
) -> Response:
    state = request.app.state.server
    if not state.try_open_request():
        raise ApiError("too many concurrent transcription requests", 429, "server_error")
    try:
        try:
            if response_format not in RESPONSE_FORMATS:
                raise ApiError(f"response_format must be one of {', '.join(RESPONSE_FORMATS)}")
            engine = state.require_engine()
            limit = state.settings.max_upload_mb * 1024 * 1024
            data = await file.read(limit + 1)
            if len(data) > limit:
                raise ApiError(f"the upload exceeds {state.settings.max_upload_mb} MB", 413)
            audio = parse_wav(data)
            text, words = await state.run(transcribe, engine, audio)
        except ApiError:
            state.metrics.requests.labels("error").inc()
            raise
        state.metrics.requests.labels("ok").inc()
        state.metrics.audio_seconds.inc(audio.duration)
    finally:
        state.close_request()

    if response_format == "text":
        return PlainTextResponse(text)
    if response_format == "srt":
        return PlainTextResponse(srt(words), media_type="application/x-subrip")
    if response_format == "vtt":
        return PlainTextResponse(vtt(words), media_type="text/vtt")
    if response_format == "verbose_json":
        return JSONResponse(
            {
                "task": "transcribe",
                "language": language or engine.language,
                "duration": audio.duration,
                "text": text,
                "words": [w.to_json() for w in words],
            }
        )
    return JSONResponse({"text": text})

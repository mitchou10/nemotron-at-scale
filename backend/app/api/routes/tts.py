"""Text-to-speech routes: the gateway to the registered `tts_service` instances."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.services.tts_pool import NoInstanceError, TtsPool

router = APIRouter(tags=["tts"])

PASSED_HEADERS = ("x-voice",)


def _error(message: str, status_code: int, error_type: str = "server_error") -> JSONResponse:
    """Same shape as OpenAI and tts_service, so one client handles every error."""
    return JSONResponse({"error": {"message": message, "type": error_type}}, status_code)


async def _relay(request: Request, method: str, path: str, body: bytes | None = None) -> Response:
    pool: TtsPool | None = getattr(request.app.state, "tts_pool", None)
    if pool is None:
        return _error("text-to-speech is not available", 503)
    try:
        if method == "POST":
            content_type = request.headers.get("content-type", "application/json")
            upstream = await pool.post(path, body or b"", content_type)
        else:
            upstream = await pool.get(path)
    except NoInstanceError as exc:
        return _error(str(exc), exc.status_code)
    return StreamingResponse(
        upstream.chunks,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers={k: v for k in PASSED_HEADERS if (v := upstream.headers.get(k))},
        background=upstream.cleanup,
    )


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

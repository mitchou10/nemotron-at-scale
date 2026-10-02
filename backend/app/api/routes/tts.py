"""Text-to-speech routes: a thin relay to the OpenAI-compatible `tts_service`."""

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

router = APIRouter(tags=["tts"])

PASSED_HEADERS = ("x-voice",)


def _error(message: str, status_code: int, error_type: str = "server_error") -> JSONResponse:
    """Same shape as OpenAI and tts_service, so one client handles every error."""
    return JSONResponse({"error": {"message": message, "type": error_type}}, status_code)


async def _relay(request: Request, method: str, path: str, body: bytes | None = None) -> Response:
    client: httpx.AsyncClient | None = getattr(request.app.state, "tts", None)
    if client is None:
        return _error("text-to-speech is disabled (set TTS_ENABLED=true)", 503)
    headers = {"content-type": request.headers.get("content-type", "application/json")}
    try:
        upstream = await client.send(
            client.build_request(method, path, content=body, headers=headers), stream=True
        )
    except httpx.HTTPError:
        return _error("the text-to-speech service is unreachable", 502)
    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers={k: v for k in PASSED_HEADERS if (v := upstream.headers.get(k))},
        background=BackgroundTask(upstream.aclose),
    )


@router.post("/audio/speech")
async def speech(request: Request) -> Response:
    """OpenAI-compatible `POST /audio/speech`: `{model, input, voice, response_format, speed}`.

    Point an OpenAI client at `<backend>/api/v1` as its base URL. The audio is relayed as it is
    synthesized (mp3 and pcm), so the first sentence can play before the last one is done.
    """
    return await _relay(request, "POST", "/v1/audio/speech", await request.body())


@router.get("/audio/voices")
async def voices(request: Request) -> Response:
    """Voices installed on the text-to-speech service."""
    return await _relay(request, "GET", "/v1/audio/voices")

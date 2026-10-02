"""POST /v1/audio/speech: text to speech, compatible with the OpenAI API."""

import time
from collections.abc import AsyncIterator, Iterator

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import require_api_key
from app.engine import AudioChunk, Engine
from app.errors import ApiError
from app.formats import CONTENT_TYPES, STREAMABLE, make_encoder, validate_format
from app.state import ServerState

router = APIRouter()

# OpenAI voice names. Clients written for OpenAI send one of these: they are spread over the
# installed Piper voices, so that "alloy" and "echo" differ when several voices are loaded.
OPENAI_VOICES = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
)


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")  # `instructions`, `stream_format`... are accepted

    model: str = "tts-1"
    input: str
    voice: str
    response_format: str = "mp3"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


def resolve_voice(engine: Engine, requested: str) -> str:
    ids = [v.id for v in engine.voices]
    if requested in ids:
        return requested
    if requested.lower() in OPENAI_VOICES:
        return ids[OPENAI_VOICES.index(requested.lower()) % len(ids)]
    raise ApiError(
        f"unknown voice '{requested}'; use one of: {', '.join(ids)} "
        f"(or an OpenAI voice name such as alloy)"
    )


async def _chunks(
    state: ServerState, iterator: Iterator[AudioChunk], first: AudioChunk
) -> AsyncIterator[AudioChunk]:
    yield first
    while (chunk := await state.run(next, iterator, None)) is not None:
        yield chunk


@router.post("/v1/audio/speech", dependencies=[Depends(require_api_key)])
async def speech(body: SpeechRequest, request: Request) -> Response:
    state: ServerState = request.app.state.server
    engine = state.require_engine()

    text = body.input.strip()
    if not text:
        raise ApiError("`input` is empty")
    if len(text) > state.settings.max_input_chars:
        raise ApiError(f"`input` is longer than {state.settings.max_input_chars} characters")
    fmt = validate_format(body.response_format)
    voice = resolve_voice(engine, body.voice)

    if not state.try_open_request():
        raise ApiError("the server is at capacity, retry shortly", 429, "rate_limit_error")

    started = time.perf_counter()
    iterator = engine.synthesize(text, voice, body.speed)
    try:
        first = await state.run(next, iterator, None)
        if first is None:
            raise ApiError("`input` has nothing to say")
    except Exception as exc:
        state.close_request()
        state.metrics.requests.labels("error").inc()
        if isinstance(exc, ApiError):
            raise
        raise ApiError(f"synthesis failed: {exc}", 500, "server_error") from exc
    state.metrics.first_audio_seconds.observe(time.perf_counter() - started)

    async def audio() -> AsyncIterator[bytes]:
        encoder = make_encoder(fmt, first.sample_rate, state.settings.mp3_bitrate)
        seconds = 0.0
        ok = False
        try:
            async for chunk in _chunks(state, iterator, first):
                seconds += len(chunk.pcm) / 2 / chunk.sample_rate
                if data := encoder.encode(chunk.pcm):
                    yield data
            if data := encoder.finish():
                yield data
            ok = True
        finally:
            state.close_request()
            state.metrics.requests.labels("ok" if ok else "error").inc()
            state.metrics.characters.inc(len(text))
            state.metrics.audio_seconds.inc(seconds)
            state.metrics.synthesis_seconds.observe(time.perf_counter() - started)

    headers = {"X-Voice": voice}
    if fmt in STREAMABLE:
        # Sent while it is being synthesized: the first sentence plays before the last is done.
        return StreamingResponse(audio(), media_type=CONTENT_TYPES[fmt], headers=headers)

    # wav and flac carry the audio length in their header: build the whole file first.
    body_bytes = b"".join([part async for part in audio()])
    return Response(body_bytes, media_type=CONTENT_TYPES[fmt], headers=headers)

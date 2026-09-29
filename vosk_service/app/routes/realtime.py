"""WebSocket /v1/audio/transcriptions/realtime: live PCM16 transcription (nemo-speech protocol)."""

import asyncio
import base64
import binascii
import json
from typing import Any

from fastapi import APIRouter, WebSocket, status
from fastapi.responses import JSONResponse

from app.auth import websocket_authorized
from app.errors import error_body
from app.session import InvalidRequestError, RealtimeSession, error_event

router = APIRouter()

REALTIME_DESCRIPTION = """
**This is a WebSocket endpoint.** Connect with `ws://` (or `wss://`); a plain HTTP request only
returns this description. Aliases: `/v1/realtime` and `/realtime`.

**Client to server**

- `{"type": "session.update", "session": {"sample_rate": 16000, "word_timestamps": false,
  "endpointing_ms": 0}}` (optional, before the first audio; `sample_rate` 8000-96000)
- binary frames: little-endian mono PCM16 audio, or
  `{"type": "input_audio_buffer.append", "audio": "<base64 PCM16>"}`
- `{"type": "input_audio_buffer.commit"}`: finish the segment and get the final transcript
- `{"type": "input_audio_buffer.clear"}` or `{"type": "response.cancel"}`: drop the audio so far

**Server to client** (every event has an `event_id`)

- `session.created`, `session.updated`
- `conversation.item.input_audio_transcription.delta`: `delta` is the text added since the previous
  partial (the full text if the partial was revised), with `audio_processed` in seconds
- `conversation.item.input_audio_transcription.completed`: `transcript` (and `words` with
  `word_timestamps`); sent on commit, or at each end of utterance with `endpointing`
- `input_audio_buffer.committed`, `input_audio_buffer.cleared`
- `error`: `{"error": {"message": "...", "type": "..."}}`; at capacity the connection is closed
  with code 1013

With an API key set, pass `Authorization: Bearer <key>` or `?api_key=<key>`.
"""


async def _handle(state: Any, session: RealtimeSession, message: dict[str, Any]) -> list[Any]:
    if (data := message.get("bytes")) is not None:
        return await state.run(session.feed, data)  # type: ignore[no-any-return]

    try:
        payload = json.loads(message.get("text") or "")
        kind = payload["type"]
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidRequestError("expected a JSON event with a `type`") from exc

    if kind == "session.update":
        return [session.update(payload.get("session") or {})]
    if kind == "input_audio_buffer.append":
        try:
            audio = base64.b64decode(payload.get("audio", ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidRequestError("`audio` must be base64-encoded PCM16") from exc
        return await state.run(session.feed, audio)  # type: ignore[no-any-return]
    if kind == "input_audio_buffer.commit":
        return await state.run(session.commit)  # type: ignore[no-any-return]
    if kind in ("input_audio_buffer.clear", "response.cancel"):
        return session.clear()
    raise InvalidRequestError(f"unsupported realtime event type: {kind}")


@router.get(
    "/v1/audio/transcriptions/realtime",
    tags=["realtime"],
    summary="Live transcription (WebSocket)",
    description=REALTIME_DESCRIPTION,
    status_code=status.HTTP_426_UPGRADE_REQUIRED,
    responses={426: {"description": "Not a WebSocket connection: use ws:// or wss://."}},
)
async def realtime_documentation() -> JSONResponse:
    """Documents the WebSocket route in the OpenAPI page (which cannot list WebSockets)."""
    body = error_body("this route is a WebSocket endpoint: connect with ws:// or wss://")
    return JSONResponse(body, status_code=426, headers={"Upgrade": "websocket"})


@router.websocket("/v1/audio/transcriptions/realtime")
@router.websocket("/v1/realtime")
@router.websocket("/realtime")
async def realtime(websocket: WebSocket) -> None:
    state = websocket.app.state.server
    if not websocket_authorized(websocket, state.settings.api_key):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid bearer token")
        return

    await websocket.accept()
    if not state.ready:
        await websocket.send_json(error_event("the model is not loaded", "server_error"))
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return
    if not state.try_open_stream():
        await websocket.send_json(error_event("the server is at capacity", "server_error"))
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    session = RealtimeSession(
        state.engine,
        state.metrics,
        endpointing=state.settings.endpointing,
        max_seconds=state.settings.max_stream_seconds,
    )
    try:
        await websocket.send_json(session.created())
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive(), timeout=state.settings.idle_timeout_s or None
                )
            except TimeoutError:
                state.metrics.idle_closed.inc()
                limit = f"{state.settings.idle_timeout_s:g}"
                await websocket.send_json(error_event(f"closed after {limit} s without data"))
                await websocket.close(code=status.WS_1001_GOING_AWAY)
                break
            if message["type"] == "websocket.disconnect":
                break
            try:
                events = await _handle(state, session, message)
            except InvalidRequestError as exc:
                events = [error_event(str(exc))]
            for item in events:
                await websocket.send_json(item)
    finally:
        state.close_stream()

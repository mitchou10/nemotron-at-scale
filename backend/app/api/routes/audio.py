"""WebSocket route receiving an audio stream from an identified client."""

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, status

from app.services.transcription import (
    Transcriber,
    TranscriberBusyError,
    TranscriberUnavailableError,
    TranscriptionSession,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audio"])

active_clients: set[str] = set()


async def _forward_events(session: TranscriptionSession, websocket: WebSocket) -> None:
    try:
        async for event in session.events():
            await websocket.send_json(event.to_json())
    except TranscriberUnavailableError:
        logger.warning("transcription service dropped the connection")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="transcription lost")


@router.websocket("/ws/audio/{client_id}")
async def audio_stream(websocket: WebSocket, client_id: str) -> None:
    """Receive PCM 16 kHz mono 16-bit chunks and stream back JSON transcripts.

    `client_id` identifies who is connected. Send the text message "end" to flush the
    current segment; replies are `{"type": "partial"|"final", "text": "..."}`.
    """
    if client_id in active_clients:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="client_id already connected"
        )
        return

    await websocket.accept()
    active_clients.add(client_id)
    logger.info("audio client connected: %s", client_id)

    transcriber: Transcriber | None = websocket.app.state.transcriber
    session: TranscriptionSession | None = None
    forwarder: asyncio.Task[None] | None = None

    try:
        if transcriber:
            session = await transcriber.open_session(client_id)
            forwarder = asyncio.create_task(_forward_events(session, websocket))

        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if session is None:
                continue
            if message.get("bytes") is not None:
                await session.send_audio(message["bytes"])
            elif message.get("text") == "end":
                await session.end()
    except TranscriberBusyError:
        logger.warning("transcription capacity exhausted for %s", client_id)
        await websocket.close(
            code=status.WS_1013_TRY_AGAIN_LATER, reason="transcription capacity exhausted"
        )
    except TranscriberUnavailableError:
        logger.warning("transcription service unavailable for %s", client_id)
        await websocket.close(
            code=status.WS_1011_INTERNAL_ERROR, reason="transcription service unavailable"
        )
    finally:
        if forwarder:
            forwarder.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await forwarder
        if session:
            await session.close()
        active_clients.discard(client_id)
        logger.info("audio client disconnected: %s", client_id)

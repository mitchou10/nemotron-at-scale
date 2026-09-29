"""WebSocket route receiving an audio stream from an identified client."""
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audio"])

active_clients: set[str] = set()


@router.websocket("/ws/audio/{client_id}")
async def audio_stream(websocket: WebSocket, client_id: str) -> None:
    """Receive binary audio chunks; `client_id` identifies who is connected."""
    if client_id in active_clients:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="client_id already connected"
        )
        return

    await websocket.accept()
    active_clients.add(client_id)
    logger.info("audio client connected: %s", client_id)

    try:
        while True:
            chunk = await websocket.receive_bytes()
            # TODO: forward `chunk` to the audio processing pipeline
            logger.debug("audio chunk from %s: %d bytes", client_id, len(chunk))
    except WebSocketDisconnect:
        pass
    finally:
        active_clients.discard(client_id)
        logger.info("audio client disconnected: %s", client_id)

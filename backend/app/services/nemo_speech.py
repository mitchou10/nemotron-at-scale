"""Client for a `nemo-speech serve` instance (NeMo-Speech.cpp realtime transcription WebSocket)."""

import json
import logging
from collections.abc import AsyncIterator

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from app.services.transcription import (
    TranscriberUnavailableError,
    TranscriptEvent,
    TranscriptionSession,
)

logger = logging.getLogger(__name__)

DELTA = "conversation.item.input_audio_transcription.delta"
COMPLETED = "conversation.item.input_audio_transcription.completed"


class NemoSpeechSession:
    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection
        self._partial = ""

    async def send_audio(self, pcm: bytes) -> None:
        try:
            await self._connection.send(pcm)
        except WebSocketException as exc:
            raise TranscriberUnavailableError(str(exc)) from exc

    async def end(self) -> None:
        try:
            await self._connection.send(json.dumps({"type": "input_audio_buffer.commit"}))
        except WebSocketException as exc:
            raise TranscriberUnavailableError(str(exc)) from exc

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        try:
            async for raw in self._connection:
                message = json.loads(raw)
                kind = message.get("type")
                if kind == DELTA:
                    self._partial += message.get("delta", "")
                    yield TranscriptEvent("partial", self._partial)
                elif kind == COMPLETED:
                    self._partial = ""
                    if message.get("transcript"):
                        yield TranscriptEvent("final", message["transcript"])
                elif kind == "input_audio_buffer.committed":
                    yield TranscriptEvent("committed", "")
                elif kind == "error":
                    logger.warning("nemo-speech error: %s", message.get("error"))
        except WebSocketException as exc:
            raise TranscriberUnavailableError(str(exc)) from exc

    async def close(self) -> None:
        await self._connection.close()


class NemoSpeechTranscriber:
    def __init__(self, url: str, api_key: str | None = None) -> None:
        self._url = url
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else None

    async def open_session(self) -> TranscriptionSession:
        try:
            connection = await connect(
                self._url, additional_headers=self._headers, max_size=None, open_timeout=5
            )
        except (OSError, TimeoutError, WebSocketException) as exc:
            raise TranscriberUnavailableError(str(exc)) from exc
        return NemoSpeechSession(connection)

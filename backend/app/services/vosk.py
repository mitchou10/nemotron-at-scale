"""Client for a Vosk (Kaldi) WebSocket server (alphacep/vosk-server).

Protocol: a JSON `config` message, then binary PCM chunks. The server answers every message
exactly once, with `{"partial": ...}` or, when its endpointer closes an utterance,
`{"text": ...}`. The message `{"eof" : 1}` returns the final result and makes the server close
the connection; the session then reconnects when more audio arrives. (Newer servers also
accept `{"reset" : 1}`, but the published Docker images do not, so it is not used.)
"""

import asyncio
import contextlib
import json
from collections import deque
from collections.abc import AsyncIterator

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from app.services.transcription import (
    TranscriberUnavailableError,
    TranscriptEvent,
    TranscriptionSession,
)

SAMPLE_RATE = 16_000
EOF = '{"eof" : 1}'  # the server compares this exact string
# After an utterance closed by the server, keep this much recent audio for failover replay:
# it covers audio that was already in flight while the result travelled back.
ENDPOINT_KEEP_MS = 500

_AUDIO = "audio"
_EOF = "eof"

_Item = TranscriptEvent | Exception | None


async def _open(url: str) -> ClientConnection:
    try:
        connection = await connect(url, max_size=None, open_timeout=5)
        await connection.send(json.dumps({"config": {"sample_rate": SAMPLE_RATE}}))
    except (OSError, TimeoutError, WebSocketException) as exc:
        raise TranscriberUnavailableError(str(exc)) from exc
    return connection


class VoskSession:
    def __init__(self, url: str, connection: ClientConnection) -> None:
        self._url = url
        self._connection: ClientConnection | None = connection
        self._sent: deque[str] = deque()  # kind of each message awaiting its reply
        self._partial = ""
        self._queue: asyncio.Queue[_Item] = asyncio.Queue()
        self._reader: asyncio.Task[None] = asyncio.create_task(self._read(connection, self._sent))
        self._closing = False

    async def _read(self, connection: ClientConnection, sent: deque[str]) -> None:
        expected_close = False
        try:
            async for raw in connection:
                kind = sent.popleft() if sent else _AUDIO
                for event in self._translate(kind, json.loads(raw)):
                    self._queue.put_nowait(event)
                expected_close = kind == _EOF
        except WebSocketException as exc:
            self._queue.put_nowait(TranscriberUnavailableError(str(exc)))
            return
        if not expected_close and not self._closing:
            self._queue.put_nowait(TranscriberUnavailableError("vosk server closed the stream"))

    async def _connected(self) -> tuple[ClientConnection, deque[str]]:
        if self._connection is None:
            await self._reader  # deliver the previous utterance's result first
            self._sent = deque()
            self._connection = await _open(self._url)
            self._reader = asyncio.create_task(self._read(self._connection, self._sent))
        return self._connection, self._sent

    async def send_audio(self, pcm: bytes) -> None:
        connection, sent = await self._connected()
        sent.append(_AUDIO)
        try:
            await connection.send(pcm)
        except WebSocketException as exc:
            raise TranscriberUnavailableError(str(exc)) from exc

    async def end(self) -> None:
        if self._connection is None:
            await self._reader
            self._queue.put_nowait(TranscriptEvent("committed", ""))
            return
        connection, sent = self._connection, self._sent
        sent.append(_EOF)
        self._connection = None
        try:
            await connection.send(EOF)
        except WebSocketException as exc:
            raise TranscriberUnavailableError(str(exc)) from exc

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    def _translate(self, kind: str, message: dict[str, object]) -> list[TranscriptEvent]:
        if "partial" in message:
            partial = str(message["partial"])
            if not partial or partial == self._partial:
                return []
            self._partial = partial
            return [TranscriptEvent("partial", partial)]

        self._partial = ""
        events: list[TranscriptEvent] = []
        if text := str(message.get("text", "")):
            events.append(TranscriptEvent("final", text))
        if kind == _EOF:
            events.append(TranscriptEvent("committed", ""))
        else:
            events.append(TranscriptEvent("trim", "", keep_ms=ENDPOINT_KEEP_MS))
        return events

    async def close(self) -> None:
        self._closing = True
        if self._connection is not None:
            await self._connection.close()
        self._reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader
        self._queue.put_nowait(None)


class VoskTranscriber:
    def __init__(self, url: str) -> None:
        self._url = url

    async def open_session(self) -> TranscriptionSession:
        return VoskSession(self._url, await _open(self._url))

    async def ping(self) -> bool:
        """The server has no health route: a successful WebSocket handshake means ready."""
        try:
            connection = await connect(self._url, open_timeout=2)
        except (OSError, TimeoutError, WebSocketException):
            return False
        await connection.close()
        return True

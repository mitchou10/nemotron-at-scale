"""Audio WebSocket tests."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.routes.audio import active_clients
from app.services.transcription import (
    TranscriberBusyError,
    TranscriberUnavailableError,
    TranscriptEvent,
)

URL = "/api/v1/ws/audio/{}"


def test_tracks_client_id_while_connected(ws_client: TestClient) -> None:
    with ws_client.websocket_connect(URL.format("alice")) as ws:
        ws.send_bytes(b"\x00\x01")
        assert "alice" in active_clients
    assert "alice" not in active_clients


def test_accepts_many_chunks(ws_client: TestClient) -> None:
    with ws_client.websocket_connect(URL.format("alice")) as ws:
        for _ in range(50):
            ws.send_bytes(b"\x00" * 320)
        assert active_clients == {"alice"}


def test_different_ids_can_connect_simultaneously(ws_client: TestClient) -> None:
    with (
        ws_client.websocket_connect(URL.format("alice")),
        ws_client.websocket_connect(URL.format("bob")),
    ):
        assert active_clients == {"alice", "bob"}
    assert active_clients == set()


def test_duplicate_id_rejected_and_first_client_kept(ws_client: TestClient) -> None:
    with ws_client.websocket_connect(URL.format("bob")):
        with (
            pytest.raises(WebSocketDisconnect) as exc,
            ws_client.websocket_connect(URL.format("bob")),
        ):
            pass
        assert exc.value.code == 1008
        assert active_clients == {"bob"}


def test_id_reusable_after_disconnect(ws_client: TestClient) -> None:
    with ws_client.websocket_connect(URL.format("carol")):
        pass
    with ws_client.websocket_connect(URL.format("carol")) as ws:
        ws.send_bytes(b"\x01")
        assert "carol" in active_clients


class FakeSession:
    def __init__(self, *, fail_on_audio: bool = False, drop: bool = False) -> None:
        self.audio: list[bytes] = []
        self.ended = False
        self.closed = False
        self._fail_on_audio = fail_on_audio
        self._drop = drop
        self._queue: asyncio.Queue[TranscriptEvent] = asyncio.Queue()

    async def send_audio(self, pcm: bytes) -> None:
        if self._fail_on_audio:
            raise TranscriberUnavailableError("down")
        self.audio.append(pcm)
        await self._queue.put(TranscriptEvent("partial", f"chunk {len(self.audio)}"))

    async def end(self) -> None:
        self.ended = True
        await self._queue.put(TranscriptEvent("final", "done"))

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        if self._drop:
            raise TranscriberUnavailableError("dropped")
        while True:
            yield await self._queue.get()

    async def close(self) -> None:
        self.closed = True


class FakeTranscriber:
    def __init__(
        self,
        session: FakeSession | None = None,
        *,
        unavailable: bool = False,
        busy: bool = False,
    ) -> None:
        self.session = session or FakeSession()
        self._unavailable = unavailable
        self._busy = busy

    async def open_session(self, client_id: str) -> FakeSession:
        if self._busy:
            raise TranscriberBusyError("full")
        if self._unavailable:
            raise TranscriberUnavailableError("down")
        return self.session


def test_transcripts_streamed_back_as_json(ws_client: TestClient) -> None:
    transcriber = FakeTranscriber()
    ws_client.app.state.transcriber = transcriber
    with ws_client.websocket_connect(URL.format("dave")) as ws:
        ws.send_bytes(b"\x00\x00")
        assert ws.receive_json() == {"type": "partial", "text": "chunk 1"}
        ws.send_text("end")
        assert ws.receive_json() == {"type": "final", "text": "done"}
    assert transcriber.session.audio == [b"\x00\x00"]
    assert transcriber.session.ended
    assert transcriber.session.closed


def test_unknown_text_message_ignored(ws_client: TestClient) -> None:
    ws_client.app.state.transcriber = FakeTranscriber()
    with ws_client.websocket_connect(URL.format("erin")) as ws:
        ws.send_text("hello")
        ws.send_bytes(b"\x00\x00")
        assert ws.receive_json() == {"type": "partial", "text": "chunk 1"}


def test_closes_1011_when_service_unavailable(ws_client: TestClient) -> None:
    ws_client.app.state.transcriber = FakeTranscriber(unavailable=True)
    with (
        ws_client.websocket_connect(URL.format("frank")) as ws,
        pytest.raises(WebSocketDisconnect) as exc,
    ):
        ws.receive_json()
    assert exc.value.code == 1011
    assert "frank" not in active_clients


def test_closes_1011_when_service_fails_mid_stream(ws_client: TestClient) -> None:
    session = FakeSession(fail_on_audio=True)
    ws_client.app.state.transcriber = FakeTranscriber(session)
    with ws_client.websocket_connect(URL.format("gina")) as ws:
        ws.send_bytes(b"\x00\x00")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1011
    assert session.closed


def test_closes_1011_when_service_drops_connection(ws_client: TestClient) -> None:
    ws_client.app.state.transcriber = FakeTranscriber(FakeSession(drop=True))
    with (
        ws_client.websocket_connect(URL.format("hank")) as ws,
        pytest.raises(WebSocketDisconnect) as exc,
    ):
        ws.receive_json()
    assert exc.value.code == 1011


def test_closes_1013_when_capacity_exhausted(ws_client: TestClient) -> None:
    ws_client.app.state.transcriber = FakeTranscriber(busy=True)
    with (
        ws_client.websocket_connect(URL.format("ivy")) as ws,
        pytest.raises(WebSocketDisconnect) as exc,
    ):
        ws.receive_json()
    assert exc.value.code == 1013

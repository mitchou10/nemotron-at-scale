"""Audio WebSocket tests."""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.routes.audio import active_clients

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

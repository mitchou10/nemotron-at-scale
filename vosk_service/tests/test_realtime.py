"""WebSocket protocol tests."""

import base64

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.session import COMPLETED, DELTA
from tests.conftest import END, FakeEngine

PATH = "/v1/audio/transcriptions/realtime"
CHUNK = b"\x01\x00" * 160


def test_session_created_then_deltas_then_commit(client: TestClient) -> None:
    with client.websocket_connect(PATH) as ws:
        created = ws.receive_json()
        assert created["type"] == "session.created"
        assert created["session"]["model"] == "vosk-model-small-fr-0.22"

        ws.send_bytes(CHUNK)
        assert ws.receive_json()["delta"] == "bonjour"
        ws.send_bytes(CHUNK)
        assert ws.receive_json()["delta"] == " tout"

        ws.send_json({"type": "input_audio_buffer.commit"})
        completed = ws.receive_json()
        assert (completed["type"], completed["transcript"]) == (COMPLETED, "bonjour tout")
        assert ws.receive_json()["type"] == "input_audio_buffer.committed"

        ws.send_bytes(CHUNK)  # the stream continues after a commit
        assert ws.receive_json()["type"] == DELTA


def test_base64_append(client: TestClient) -> None:
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        audio = base64.b64encode(CHUNK).decode()
        ws.send_json({"type": "input_audio_buffer.append", "audio": audio})
        assert ws.receive_json()["delta"] == "bonjour"


def test_session_update_before_audio(client: TestClient, engine: FakeEngine) -> None:
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_json({"type": "session.update", "session": {"sample_rate": 8000}})
        assert ws.receive_json()["type"] == "session.updated"
        ws.send_bytes(CHUNK)
        ws.receive_json()
    assert engine.created[0].rate == 8000


def test_session_update_after_audio_is_an_error(client: TestClient) -> None:
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_bytes(CHUNK)
        ws.receive_json()
        ws.send_json({"type": "session.update", "session": {}})
        error = ws.receive_json()
        assert error["type"] == "error"
        assert error["error"] == {
            "message": "session.update is rejected once audio has started",
            "type": "invalid_request_error",
        }
        ws.send_bytes(CHUNK)  # the session survives the error
        assert ws.receive_json()["type"] == DELTA


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("not json", "expected a JSON event"),
        ('{"no": "type"}', "expected a JSON event"),
        ("[1]", "expected a JSON event"),
        ('{"type": "nope"}', "unsupported realtime event type: nope"),
        ('{"type": "input_audio_buffer.append", "audio": "@@@"}', "base64"),
    ],
)
def test_bad_events_are_reported_and_the_connection_survives(
    client: TestClient, message: str, expected: str
) -> None:
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_text(message)
        error = ws.receive_json()
        assert error["type"] == "error"
        assert expected in error["error"]["message"]
        ws.send_bytes(CHUNK)
        assert ws.receive_json()["type"] == DELTA


@pytest.mark.parametrize("kind", ["input_audio_buffer.clear", "response.cancel"])
def test_clear_and_cancel_drop_the_audio(client: TestClient, kind: str) -> None:
    with client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_bytes(CHUNK)
        ws.receive_json()
        ws.send_json({"type": kind})
        assert ws.receive_json()["type"] == "input_audio_buffer.cleared"
        ws.send_json({"type": "input_audio_buffer.commit"})
        assert ws.receive_json()["type"] == "input_audio_buffer.committed"  # nothing to complete


def test_endpointing_setting_emits_completed_mid_stream(engine: FakeEngine) -> None:
    settings = Settings(_env_file=None, endpointing=True, max_streams=2)
    with TestClient(create_app(settings, engine)) as client, client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_bytes(CHUNK)
        ws.receive_json()
        ws.send_bytes(END)
        assert ws.receive_json()["transcript"] == "bonjour"


@pytest.mark.parametrize("alias", ["/v1/realtime", "/realtime"])
def test_route_aliases(client: TestClient, alias: str) -> None:
    with client.websocket_connect(alias) as ws:
        assert ws.receive_json()["type"] == "session.created"


def test_at_capacity_new_streams_are_refused_and_slots_are_freed(client: TestClient) -> None:
    server = client.app.state.server
    with client.websocket_connect(PATH) as first, client.websocket_connect(PATH) as second:
        first.receive_json()
        second.receive_json()
        assert server.active_streams == 2
        assert client.get("/ready").json()["active_streams"] == 2

        with client.websocket_connect(PATH) as third:
            error = third.receive_json()
            assert error["error"]["message"] == "the server is at capacity"
            assert error["error"]["type"] == "server_error"
            with pytest.raises(WebSocketDisconnect) as closed:
                third.receive_json()
            assert closed.value.code == 1013

    assert server.active_streams == 0
    text = client.get("/metrics").text
    assert "vosk_streams_rejected_total 1.0" in text
    assert "vosk_streams_total 2.0" in text
    with client.websocket_connect(PATH) as again:
        assert again.receive_json()["type"] == "session.created"


def test_streams_are_refused_until_the_model_is_loaded(settings: Settings) -> None:
    with TestClient(create_app(settings, engine=None, load_model=False)) as client:
        client.app.state.server.engine = None
        with client.websocket_connect(PATH) as ws:
            assert ws.receive_json()["error"]["message"] == "the model is not loaded"
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1013


def test_websocket_api_key(engine: FakeEngine) -> None:
    settings = Settings(_env_file=None, api_key="secret", max_streams=4)
    with TestClient(create_app(settings, engine)) as client:
        with pytest.raises(WebSocketDisconnect) as refused, client.websocket_connect(PATH):
            pass
        assert refused.value.code == 1008

        with client.websocket_connect(f"{PATH}?api_key=secret") as by_query:
            assert by_query.receive_json()["type"] == "session.created"
        headers = {"Authorization": "Bearer secret"}
        with client.websocket_connect(PATH, headers=headers) as by_header:
            assert by_header.receive_json()["type"] == "session.created"
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"{PATH}?api_key=no"):
            pass


def test_idle_streams_are_closed_and_free_their_slot(engine: FakeEngine) -> None:
    settings = Settings(_env_file=None, max_streams=1, idle_timeout_s=0.2)
    with TestClient(create_app(settings, engine)) as client, client.websocket_connect(PATH) as ws:
        ws.receive_json()
        error = ws.receive_json()  # nothing is sent: the server gives up
        assert error["type"] == "error"
        assert "without data" in error["error"]["message"]
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1001
        assert "vosk_streams_closed_idle_total 1.0" in client.get("/metrics").text
        assert client.app.state.server.active_streams == 0


def test_activity_keeps_a_stream_alive_past_the_idle_timeout(engine: FakeEngine) -> None:
    import time

    settings = Settings(_env_file=None, max_streams=1, idle_timeout_s=0.5)
    with TestClient(create_app(settings, engine)) as client, client.websocket_connect(PATH) as ws:
        ws.receive_json()
        for _ in range(4):
            time.sleep(0.2)
            ws.send_bytes(CHUNK)
            assert ws.receive_json()["type"] == DELTA


def test_idle_timeout_zero_disables_it(engine: FakeEngine) -> None:
    import time

    settings = Settings(_env_file=None, max_streams=1, idle_timeout_s=0)
    with TestClient(create_app(settings, engine)) as client, client.websocket_connect(PATH) as ws:
        ws.receive_json()
        time.sleep(0.3)
        ws.send_bytes(CHUNK)
        assert ws.receive_json()["type"] == DELTA


def test_stream_duration_limit_is_reported_as_an_error(engine: FakeEngine) -> None:
    settings = Settings(_env_file=None, max_streams=1, max_stream_seconds=1)
    with TestClient(create_app(settings, engine)) as client, client.websocket_connect(PATH) as ws:
        ws.receive_json()
        ws.send_bytes(b"\x01\x00" * 16_000)  # exactly 1 s: allowed
        assert ws.receive_json()["type"] == DELTA
        ws.send_bytes(b"\x01\x00")
        error = ws.receive_json()
        assert error["type"] == "error"
        assert "maximum duration of 1 seconds" in error["error"]["message"]

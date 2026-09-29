"""App wiring: background model loading, settings and metrics."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings, get_settings
from app.main import create_app
from tests.conftest import FakeEngine


def wait_until(check, timeout: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_model_loads_in_the_background(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(
        main, "_load_engine", lambda _settings: FakeEngine("vosk-model-en-us-0.22", "en-us")
    )
    with TestClient(create_app(settings)) as client:
        wait_until(lambda: client.get("/ready").status_code == 200)
        assert client.get("/ready").json()["model"] == "vosk-model-en-us-0.22"


def test_loading_failure_is_reported_and_the_server_stays_up(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    def fail(_settings: Settings) -> FakeEngine:
        raise RuntimeError("no such model")

    monkeypatch.setattr(main, "_load_engine", fail)
    with TestClient(create_app(settings)) as client:
        wait_until(lambda: client.get("/ready").json().get("detail") == "no such model")
        assert client.get("/health").status_code == 503
        assert client.get("/").status_code == 200


def test_load_engine_uses_the_real_engine(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    from app import vosk_engine

    monkeypatch.setattr(vosk_engine.VoskEngine, "load", classmethod(lambda cls, s: "engine"))
    assert main._load_engine(settings) == "engine"


def test_default_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("VOSK_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("VOSK_MAX_STREAMS", "3")
    try:
        app = create_app(engine=FakeEngine())
        assert app.state.server.settings.model_dir == str(tmp_path)
        assert app.state.server.settings.max_streams == 3
    finally:
        get_settings.cache_clear()


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.port == 8080
    assert settings.model_name == "vosk-model-small-fr-0.22"
    assert settings.max_streams >= 1
    assert settings.threads >= 1
    assert settings.endpointing is False
    assert settings.api_key is None


def test_metrics_endpoint(client: TestClient) -> None:
    text = client.get("/metrics").text
    assert "vosk_active_streams 0.0" in text
    assert "process_resident_memory_bytes" in text

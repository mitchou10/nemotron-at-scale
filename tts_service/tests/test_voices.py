"""Voice name to download URL, and the download itself."""

import pytest

from app.config import Settings
from app.voices import ensure_voice, voice_path


def test_voice_path() -> None:
    assert voice_path("fr_FR-siwis-medium") == "fr/fr_FR/siwis/medium/fr_FR-siwis-medium"
    assert voice_path("en_US-lessac-low") == "en/en_US/lessac/low/en_US-lessac-low"


@pytest.mark.parametrize("name", ["siwis", "fr-siwis-medium", "../etc/passwd"])
def test_bad_voice_names(name: str) -> None:
    with pytest.raises(ValueError):
        voice_path(name)


def test_existing_voice_is_not_downloaded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "fr_FR-siwis-medium.onnx").write_bytes(b"model")
    (tmp_path / "fr_FR-siwis-medium.onnx.json").write_text("{}")
    settings = Settings(voice_dir=str(tmp_path), voice_url="http://127.0.0.1:9")
    assert ensure_voice(settings, "fr_FR-siwis-medium") == tmp_path / "fr_FR-siwis-medium.onnx"


def test_missing_voice_is_downloaded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    remote = tmp_path / "remote" / "fr" / "fr_FR" / "siwis" / "medium"
    remote.mkdir(parents=True)
    (remote / "fr_FR-siwis-medium.onnx").write_bytes(b"model")
    (remote / "fr_FR-siwis-medium.onnx.json").write_text("{}")
    settings = Settings(
        voice_dir=str(tmp_path / "voices"), voice_url=(tmp_path / "remote").as_uri()
    )
    path = ensure_voice(settings, "fr_FR-siwis-medium")
    assert path.read_bytes() == b"model"
    assert path.with_name(path.name + ".json").read_text() == "{}"
    assert not list((tmp_path / "voices").glob("*.part"))

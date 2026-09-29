"""Model directory and download tests."""

import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.engine import language_from_name
from app.models import ensure_model, is_model_dir


def make_zip(path: Path, name: str, *, with_am: bool = True) -> None:
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(f"{name}/conf/model.conf", "x")
        if with_am:
            bundle.writestr(f"{name}/am/final.mdl", "x")


def settings_for(tmp_path: Path, zip_path: Path, name: str) -> Settings:
    return Settings(
        _env_file=None,
        model_name=name,
        model_dir=str(tmp_path / "models"),
        model_url=zip_path.as_uri(),
    )


@pytest.mark.parametrize(
    ("name", "language"),
    [
        ("vosk-model-small-fr-0.22", "fr"),
        ("vosk-model-fr-0.22", "fr"),
        ("vosk-model-en-us-0.22-lgraph", "en-us"),
        ("vosk-model-small-en-us-0.15", "en-us"),
        ("whatever", "unknown"),
    ],
)
def test_language_from_name(name: str, language: str) -> None:
    assert language_from_name(name) == language


def test_is_model_dir(tmp_path: Path) -> None:
    assert not is_model_dir(tmp_path / "missing")
    (tmp_path / "empty").mkdir()
    assert not is_model_dir(tmp_path / "empty")
    (tmp_path / "ok" / "am").mkdir(parents=True)
    assert is_model_dir(tmp_path / "ok")


def test_existing_model_is_not_downloaded(tmp_path: Path) -> None:
    (tmp_path / "models" / "m" / "am").mkdir(parents=True)
    settings = Settings(
        _env_file=None,
        model_name="m",
        model_dir=str(tmp_path / "models"),
        model_url="file:///does/not/exist.zip",
    )
    assert ensure_model(settings) == tmp_path / "models" / "m"


def test_missing_model_is_downloaded_and_unpacked(tmp_path: Path) -> None:
    archive = tmp_path / "m.zip"
    make_zip(archive, "m")
    settings = settings_for(tmp_path, archive, "m")
    path = ensure_model(settings)
    assert path == tmp_path / "models" / "m"
    assert (path / "am" / "final.mdl").is_file()
    assert [p.name for p in (tmp_path / "models").iterdir()] == ["m"]  # no scratch left over


def test_archive_without_the_model_folder_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "m.zip"
    make_zip(archive, "other")
    with pytest.raises(RuntimeError, match="does not contain"):
        ensure_model(settings_for(tmp_path, archive, "m"))


def test_archive_without_acoustic_model_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "m.zip"
    make_zip(archive, "m", with_am=False)
    with pytest.raises(RuntimeError, match="does not contain"):
        ensure_model(settings_for(tmp_path, archive, "m"))


def test_concurrent_download_by_another_instance_is_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.request

    archive = tmp_path / "m.zip"
    make_zip(archive, "m")
    settings = settings_for(tmp_path, archive, "m")
    real_urlopen = urllib.request.urlopen

    def urlopen_then_lose_the_race(url: str):  # type: ignore[no-untyped-def]
        response = real_urlopen(url)
        (tmp_path / "models" / "m" / "am").mkdir(parents=True)  # the other instance won
        (tmp_path / "models" / "m" / "am" / "final.mdl").write_text("x")
        return response

    monkeypatch.setattr(urllib.request, "urlopen", urlopen_then_lose_the_race)
    assert ensure_model(settings) == tmp_path / "models" / "m"


def test_a_real_move_failure_is_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "m.zip"
    make_zip(archive, "m")

    def broken_replace(self: Path, target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", broken_replace)
    with pytest.raises(OSError, match="disk full"):
        ensure_model(settings_for(tmp_path, archive, "m"))

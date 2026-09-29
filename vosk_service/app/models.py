"""Model files: find the model in the model directory, downloading it on first start."""

import logging
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from app.config import Settings

logger = logging.getLogger(__name__)


def is_model_dir(path: Path) -> bool:
    return path.is_dir() and (path / "am").is_dir()


def ensure_model(settings: Settings) -> Path:
    """Return the directory of `settings.model_name`, downloading and unpacking it if needed."""
    root = Path(settings.model_dir)
    target = root / settings.model_name
    if is_model_dir(target):
        return target

    root.mkdir(parents=True, exist_ok=True)
    url = settings.model_url.format(name=settings.model_name)
    logger.info("downloading model %s from %s", settings.model_name, url)
    with tempfile.TemporaryDirectory(dir=root) as scratch:
        archive = Path(scratch) / "model.zip"
        with urllib.request.urlopen(url) as response, archive.open("wb") as out:  # noqa: S310
            shutil.copyfileobj(response, out)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(scratch)
        unpacked = Path(scratch) / settings.model_name
        if not is_model_dir(unpacked):
            raise RuntimeError(f"{url} does not contain a {settings.model_name}/ Vosk model")
        try:
            unpacked.replace(target)
        except OSError:
            # another instance sharing the volume unpacked the same model first
            if not is_model_dir(target):
                raise
    logger.info("model ready in %s", target)
    return target

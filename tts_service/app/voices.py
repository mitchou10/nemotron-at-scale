"""Voice files: find Piper voices in the voice directory, downloading them on first start."""

import logging
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path

from app.config import Settings

logger = logging.getLogger(__name__)

VOICE_NAME = re.compile(
    r"^(?P<lang>[a-z]{2,3})_(?P<region>[A-Z]{2})-(?P<name>[^-]+)-(?P<quality>[a-z_]+)$"
)


def voice_path(voice: str) -> str:
    """`fr_FR-siwis-medium` -> `fr/fr_FR/siwis/medium/fr_FR-siwis-medium` (rhasspy/piper-voices)."""
    match = VOICE_NAME.match(voice)
    if not match:
        raise ValueError(f"'{voice}' is not a Piper voice name (expected e.g. fr_FR-siwis-medium)")
    lang, region, name, quality = match.group("lang", "region", "name", "quality")
    return f"{lang}/{lang}_{region}/{name}/{quality}/{voice}"


def ensure_voice(settings: Settings, voice: str) -> Path:
    """Return the `.onnx` file of `voice`, downloading it (and its `.onnx.json`) if needed."""
    root = Path(settings.voice_dir)
    model = root / f"{voice}.onnx"
    config = root / f"{voice}.onnx.json"
    if model.is_file() and config.is_file():
        return model

    root.mkdir(parents=True, exist_ok=True)
    remote = f"{settings.voice_url.rstrip('/')}/{voice_path(voice)}"
    for target in (model, config):
        if target.is_file():
            continue
        url = remote + target.name.removeprefix(voice)
        logger.info("downloading %s", url)
        with tempfile.NamedTemporaryFile(dir=root, delete=False, suffix=".part") as part:
            try:
                with urllib.request.urlopen(url) as response:  # noqa: S310
                    shutil.copyfileobj(response, part)
            except Exception:
                Path(part.name).unlink(missing_ok=True)
                raise
        Path(part.name).replace(target)
    logger.info("voice %s ready in %s", voice, root)
    return model

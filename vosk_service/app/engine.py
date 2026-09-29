"""What the server needs from a speech engine (the real one wraps Vosk; tests use a fake)."""

import re
from typing import Any, Protocol


class Recognizer(Protocol):
    """One stream of audio being recognized (mirrors vosk.KaldiRecognizer, with dict results)."""

    def accept_waveform(self, data: bytes) -> bool:
        """Feed 16-bit mono PCM; True when the engine closed an utterance (`result` is ready)."""

    def result(self) -> dict[str, Any]:
        """`{"text": ..., "result": [{"word", "start", "end", "conf"}, ...]}` of the utterance."""

    def partial_result(self) -> dict[str, Any]:
        """`{"partial": ...}` of the utterance in progress."""

    def final_result(self) -> dict[str, Any]:
        """Same shape as `result`, flushing what remains."""


class Engine(Protocol):
    name: str
    language: str

    def create_recognizer(self, sample_rate: int, words: bool) -> Recognizer: ...


def language_from_name(model_name: str) -> str:
    """`vosk-model-small-fr-0.22` -> `fr`, `vosk-model-en-us-0.22-lgraph` -> `en-us`."""
    match = re.match(r"vosk-model(?:-small)?-(.+?)-\d", model_name)
    return match.group(1) if match else "unknown"

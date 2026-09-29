"""The real engine: Vosk (Kaldi). Needs the `vosk` package and a model on disk."""

import json
from typing import Any

from vosk import KaldiRecognizer, Model, SetLogLevel

from app.config import Settings
from app.engine import Recognizer, language_from_name
from app.models import ensure_model


class _KaldiStream:
    def __init__(self, recognizer: KaldiRecognizer) -> None:
        self._recognizer = recognizer

    def accept_waveform(self, data: bytes) -> bool:
        return bool(self._recognizer.AcceptWaveform(data))

    def result(self) -> dict[str, Any]:
        return json.loads(self._recognizer.Result())  # type: ignore[no-any-return]

    def partial_result(self) -> dict[str, Any]:
        return json.loads(self._recognizer.PartialResult())  # type: ignore[no-any-return]

    def final_result(self) -> dict[str, Any]:
        return json.loads(self._recognizer.FinalResult())  # type: ignore[no-any-return]


class VoskEngine:
    def __init__(self, model: Model, name: str) -> None:
        self._model = model
        self.name = name
        self.language = language_from_name(name)

    @classmethod
    def load(cls, settings: Settings) -> "VoskEngine":
        SetLogLevel(-1)
        path = ensure_model(settings)
        return cls(Model(str(path)), settings.model_name)

    def create_recognizer(self, sample_rate: int, words: bool) -> Recognizer:
        recognizer = KaldiRecognizer(self._model, float(sample_rate))
        recognizer.SetWords(words)
        return _KaldiStream(recognizer)

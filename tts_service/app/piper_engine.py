"""The real engine: Piper voices (ONNX, CPU)."""

import logging
from collections.abc import Iterator

from app.config import Settings
from app.engine import AudioChunk, VoiceInfo
from app.voices import ensure_voice

logger = logging.getLogger(__name__)


class PiperEngine:
    name = "piper"

    def __init__(self, voices: dict[str, object], info: list[VoiceInfo]) -> None:
        self._voices = voices
        self.voices = info

    @classmethod
    def load(cls, settings: Settings) -> "PiperEngine":
        from piper import PiperVoice

        loaded: dict[str, object] = {}
        info: list[VoiceInfo] = []
        for name in settings.voices:
            voice = PiperVoice.load(ensure_voice(settings, name))
            loaded[name] = voice
            language = str(voice.config.espeak_voice or name.split("-")[0])
            info.append(VoiceInfo(name, language, voice.config.sample_rate))
            logger.info("loaded voice %s (%d Hz)", name, voice.config.sample_rate)
        return cls(loaded, info)

    def synthesize(self, text: str, voice: str, speed: float) -> Iterator[AudioChunk]:
        from piper import SynthesisConfig

        # length_scale is the duration of each phoneme: the inverse of the speed
        config = SynthesisConfig(length_scale=1.0 / speed)
        for chunk in self._voices[voice].synthesize(text, config):  # type: ignore[attr-defined]
            yield AudioChunk(chunk.audio_int16_bytes, chunk.sample_rate)

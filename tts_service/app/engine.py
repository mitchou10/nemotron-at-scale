"""What the server needs from a speech engine (the real one wraps Piper; tests use a fake)."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VoiceInfo:
    id: str
    language: str
    sample_rate: int


@dataclass(frozen=True)
class AudioChunk:
    """Mono 16-bit little-endian PCM."""

    pcm: bytes
    sample_rate: int


class Engine(Protocol):
    name: str
    voices: list[VoiceInfo]

    def synthesize(self, text: str, voice: str, speed: float) -> Iterator[AudioChunk]:
        """Audio of `text`, one chunk per sentence. `speed` 1.0 is normal; 2.0 twice as fast."""

"""Model-agnostic live transcription interfaces (PCM 16 kHz mono 16-bit in, text events out)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol


class TranscriberUnavailableError(Exception):
    """The transcription service cannot be reached or dropped the connection."""


class TranscriberBusyError(TranscriberUnavailableError):
    """Every transcription instance is at capacity; retry later."""


@dataclass(frozen=True)
class TranscriptEvent:
    type: Literal["partial", "final", "committed"]
    text: str

    def to_json(self) -> dict[str, str]:
        return {"type": self.type, "text": self.text}


class TranscriptionSession(Protocol):
    async def send_audio(self, pcm: bytes) -> None: ...

    async def end(self) -> None: ...

    def events(self) -> AsyncIterator[TranscriptEvent]: ...

    async def close(self) -> None: ...


class Transcriber(Protocol):
    async def open_session(self, client_id: str) -> TranscriptionSession: ...

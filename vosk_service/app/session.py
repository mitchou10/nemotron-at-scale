"""Realtime transcription session, following the nemo-speech realtime event protocol.

Client -> server: `session.update` (optional, before audio), binary PCM16 frames or
`input_audio_buffer.append` (base64), `input_audio_buffer.commit`, `input_audio_buffer.clear`.
Server -> client: `conversation.item.input_audio_transcription.delta` (`delta`: new text since the
previous partial), `.completed` (`transcript`), `input_audio_buffer.committed` / `.cleared`,
`session.updated`, `error`.
"""

import itertools
import time
from typing import Any

from app.audio import MAX_RATE, MIN_RATE
from app.engine import Engine, Recognizer
from app.metrics import Metrics

DELTA = "conversation.item.input_audio_transcription.delta"
COMPLETED = "conversation.item.input_audio_transcription.completed"
BYTES_PER_SAMPLE = 2

_event_ids = itertools.count(1)


class InvalidRequestError(Exception):
    """A client request the session cannot honour; reported as an `error` event."""


def event(kind: str, **fields: Any) -> dict[str, Any]:
    return {"type": kind, "event_id": f"event_{next(_event_ids)}", **fields}


def error_event(message: str, error_type: str = "invalid_request_error") -> dict[str, Any]:
    return event("error", error={"message": message, "type": error_type})


def _join(parts: list[str]) -> str:
    return " ".join(part for part in parts if part)


class RealtimeSession:
    def __init__(
        self, engine: Engine, metrics: Metrics, *, endpointing: bool, max_seconds: float
    ) -> None:
        self._engine = engine
        self._metrics = metrics
        self._endpointing = endpointing
        self._max_seconds = max_seconds
        self.sample_rate = 16_000
        self.word_timestamps = False
        self._recognizer: Recognizer | None = None
        self._started = False
        self._audio_bytes = 0
        self._finalized: list[str] = []
        self._words: list[dict[str, Any]] = []
        self._previous_text = ""

    @property
    def _audio_seconds(self) -> float:
        return self._audio_bytes / (self.sample_rate * BYTES_PER_SAMPLE)

    def created(self) -> dict[str, Any]:
        return event(
            "session.created",
            session={
                "sample_rate": self.sample_rate,
                "model": self._engine.name,
                "language": self._engine.language,
            },
        )

    def update(self, session: dict[str, Any]) -> dict[str, Any]:
        if self._started:
            raise InvalidRequestError("session.update is rejected once audio has started")
        rate = session.get("sample_rate", self.sample_rate)
        if not isinstance(rate, int | float) or not MIN_RATE <= rate <= MAX_RATE:
            raise InvalidRequestError(f"sample_rate must be between {MIN_RATE} and {MAX_RATE}")
        self.sample_rate = int(rate)
        self.word_timestamps = bool(session.get("word_timestamps", False))
        if (endpointing_ms := session.get("endpointing_ms")) is not None:
            self._endpointing = float(endpointing_ms) > 0
        return event("session.updated", session=session)

    def _ensure_recognizer(self) -> Recognizer:
        if self._recognizer is None:
            self._recognizer = self._engine.create_recognizer(
                self.sample_rate, self.word_timestamps
            )
        return self._recognizer

    def feed(self, pcm: bytes) -> list[dict[str, Any]]:
        """Decode a chunk of 16-bit mono PCM (CPU-bound: call from a worker thread)."""
        if not pcm:
            return []
        self._audio_bytes += len(pcm)
        if self._audio_seconds > self._max_seconds:
            raise InvalidRequestError(
                f"the stream exceeds the maximum duration of {self._max_seconds:g} seconds"
            )
        self._started = True
        recognizer = self._ensure_recognizer()

        started = time.perf_counter()
        utterance_ended = recognizer.accept_waveform(pcm)
        if utterance_ended:
            self._collect(recognizer.result())
            events = self._complete() if self._endpointing else self._deltas(_join(self._finalized))
        else:
            partial = str(recognizer.partial_result().get("partial", ""))
            events = self._deltas(_join([*self._finalized, partial]))
        self._metrics.chunk_seconds.observe(time.perf_counter() - started)
        self._metrics.audio_seconds.inc(len(pcm) / (self.sample_rate * BYTES_PER_SAMPLE))
        return events

    def commit(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self._recognizer is not None:
            self._collect(self._recognizer.final_result())
            events = self._complete()
        self._reset()
        return [*events, event("input_audio_buffer.committed")]

    def clear(self) -> list[dict[str, Any]]:
        self._reset()
        return [event("input_audio_buffer.cleared")]

    def _reset(self) -> None:
        self._recognizer = None
        self._started = False
        self._audio_bytes = 0
        self._finalized = []
        self._words = []
        self._previous_text = ""

    def _collect(self, result: dict[str, Any]) -> None:
        if text := str(result.get("text", "")):
            self._finalized.append(text)
            self._words.extend(
                {
                    "word": w["word"],
                    "start": w["start"],
                    "end": w["end"],
                    "confidence": w.get("conf", 1.0),
                }
                for w in result.get("result", [])
            )

    def _complete(self) -> list[dict[str, Any]]:
        text = _join(self._finalized)
        events: list[dict[str, Any]] = []
        if text:
            fields: dict[str, Any] = {
                "transcript": text,
                "audio_processed": self._audio_seconds,
            }
            if self.word_timestamps:
                fields["words"] = self._words
            events.append(event(COMPLETED, **fields))
        self._finalized = []
        self._words = []
        self._previous_text = ""
        return events

    def _deltas(self, text: str) -> list[dict[str, Any]]:
        if text == self._previous_text:
            return []
        previous, self._previous_text = self._previous_text, text
        delta = text[len(previous) :] if text.startswith(previous) else text
        if not delta:
            return []
        return [event(DELTA, delta=delta, audio_processed=self._audio_seconds)]

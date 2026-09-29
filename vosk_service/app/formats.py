"""Transcription output formats: json, verbose_json, text, srt and vtt."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    word: str
    start: float
    end: float
    confidence: float

    def to_json(self) -> dict[str, object]:
        return {
            "word": self.word,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
        }


RESPONSE_FORMATS = ("json", "verbose_json", "text", "srt", "vtt")
MAX_CUE_WORDS = 10
MAX_CUE_SECONDS = 5.0
MAX_CUE_GAP = 1.0


def make_cues(words: list[Word]) -> list[tuple[float, float, str]]:
    """Group words into subtitle cues: at most 10 words / 5 s, split on pauses over 1 s."""
    cues: list[list[Word]] = []
    for word in words:
        current = cues[-1] if cues else None
        if (
            current is None
            or len(current) >= MAX_CUE_WORDS
            or word.end - current[0].start > MAX_CUE_SECONDS
            or word.start - current[-1].end > MAX_CUE_GAP
        ):
            cues.append([word])
        else:
            current.append(word)
    return [(c[0].start, c[-1].end, " ".join(w.word for w in c)) for c in cues]


def _timestamp(seconds: float, separator: str) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{millis:03}"


def srt(words: list[Word]) -> str:
    blocks = [
        f"{index}\n{_timestamp(start, ',')} --> {_timestamp(end, ',')}\n{text}\n"
        for index, (start, end, text) in enumerate(make_cues(words), start=1)
    ]
    return "\n".join(blocks)


def vtt(words: list[Word]) -> str:
    blocks = [
        f"{_timestamp(start, '.')} --> {_timestamp(end, '.')}\n{text}\n"
        for start, end, text in make_cues(words)
    ]
    return "WEBVTT\n\n" + "\n".join(blocks)

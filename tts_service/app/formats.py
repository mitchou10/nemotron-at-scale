"""Audio encoders for `response_format`: pcm, mp3, wav and flac."""

import io
import struct
from collections.abc import Callable
from typing import Protocol

from app.errors import ApiError

CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "pcm": "audio/pcm",
}
# Formats OpenAI knows but that need an encoder this service does not ship.
UNSUPPORTED = ("opus", "aac")
# Written as it comes, chunk by chunk. wav and flac need the whole audio (header sizes).
STREAMABLE = ("pcm", "mp3")


class Encoder(Protocol):
    def encode(self, pcm: bytes) -> bytes: ...

    def finish(self) -> bytes: ...


class PcmEncoder:
    def encode(self, pcm: bytes) -> bytes:
        return pcm

    def finish(self) -> bytes:
        return b""


class Mp3Encoder:
    def __init__(self, sample_rate: int, bitrate: int) -> None:
        import lameenc

        self._encoder = lameenc.Encoder()
        self._encoder.set_bit_rate(bitrate)
        self._encoder.set_in_sample_rate(sample_rate)
        self._encoder.set_channels(1)
        self._encoder.set_quality(2)

    def encode(self, pcm: bytes) -> bytes:
        return bytes(self._encoder.encode(pcm))

    def finish(self) -> bytes:
        return bytes(self._encoder.flush())


class _Buffered:
    """Collects the PCM and writes the container at the end."""

    def __init__(self, sample_rate: int) -> None:
        self._rate = sample_rate
        self._pcm = bytearray()

    def encode(self, pcm: bytes) -> bytes:
        self._pcm += pcm
        return b""

    def finish(self) -> bytes:
        raise NotImplementedError


class WavEncoder(_Buffered):
    def finish(self) -> bytes:
        size = len(self._pcm)
        header = b"RIFF" + struct.pack("<I", 36 + size) + b"WAVEfmt "
        header += struct.pack("<IHHIIHH", 16, 1, 1, self._rate, self._rate * 2, 2, 16)
        return header + b"data" + struct.pack("<I", size) + bytes(self._pcm)


class FlacEncoder(_Buffered):
    def finish(self) -> bytes:
        import numpy as np
        import soundfile

        out = io.BytesIO()
        samples = np.frombuffer(bytes(self._pcm), dtype="<i2")
        soundfile.write(out, samples, self._rate, format="FLAC", subtype="PCM_16")
        return out.getvalue()


def validate_format(name: str) -> str:
    if name in CONTENT_TYPES:
        return name
    supported = ", ".join(CONTENT_TYPES)
    if name in UNSUPPORTED:
        raise ApiError(f"response_format '{name}' is not supported; use one of: {supported}")
    raise ApiError(f"unknown response_format '{name}'; use one of: {supported}")


def make_encoder(name: str, sample_rate: int, mp3_bitrate: int) -> Encoder:
    factories: dict[str, Callable[[], Encoder]] = {
        "pcm": PcmEncoder,
        "mp3": lambda: Mp3Encoder(sample_rate, mp3_bitrate),
        "wav": lambda: WavEncoder(sample_rate),
        "flac": lambda: FlacEncoder(sample_rate),
    }
    return factories[name]()

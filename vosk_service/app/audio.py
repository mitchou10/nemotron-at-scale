"""WAV decoding: PCM16 and float32 files, 8-96 kHz, any channel count (downmixed to mono)."""

import struct
from dataclasses import dataclass

import numpy as np

from app.errors import ApiError

MIN_RATE, MAX_RATE = 8_000, 96_000


@dataclass(frozen=True)
class Audio:
    pcm: bytes  # mono, little-endian 16-bit
    sample_rate: int
    duration: float


def parse_wav(data: bytes) -> Audio:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ApiError("the uploaded file is not a RIFF/WAVE file")

    fmt: bytes | None = None
    pcm: bytes | None = None
    position = 12
    while position + 8 <= len(data):
        chunk_id = data[position : position + 4]
        (size,) = struct.unpack("<I", data[position + 4 : position + 8])
        body = data[position + 8 : position + 8 + size]
        if chunk_id == b"fmt ":
            fmt = body
        elif chunk_id == b"data":
            pcm = body
        position += 8 + size + (size & 1)
    if fmt is None or len(fmt) < 16 or pcm is None:
        raise ApiError("the WAV file has no usable fmt/data chunk")

    tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE and len(fmt) >= 26:  # WAVE_FORMAT_EXTENSIBLE: real tag is in the sub-format
        (tag,) = struct.unpack("<H", fmt[24:26])
    if not MIN_RATE <= rate <= MAX_RATE:
        raise ApiError(f"sample rate {rate} Hz is outside {MIN_RATE}-{MAX_RATE} Hz")
    if channels < 1:
        raise ApiError("the WAV file has no channel")

    if tag == 1 and bits == 16:
        samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32)
    elif tag == 3 and bits == 32:
        samples = np.frombuffer(pcm[: len(pcm) // 4 * 4], dtype="<f4") * 32768.0
    else:
        raise ApiError("only PCM16 and float32 WAV files are supported")

    frames = len(samples) // channels
    mono = samples[: frames * channels].reshape(frames, channels).mean(axis=1)
    out = np.clip(mono, -32768, 32767).astype("<i2").tobytes()
    return Audio(out, rate, frames / rate)

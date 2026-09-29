"""WAV decoding tests."""

import struct

import numpy as np
import pytest

from app.audio import parse_wav
from app.errors import ApiError
from tests.conftest import wav_bytes


def pcm16(*values: int) -> bytes:
    return struct.pack(f"<{len(values)}h", *values)


def test_mono_pcm16_is_returned_unchanged() -> None:
    audio = parse_wav(wav_bytes(pcm16(1, -2, 300), rate=16_000))
    assert audio.pcm == pcm16(1, -2, 300)
    assert audio.sample_rate == 16_000
    assert audio.duration == pytest.approx(3 / 16_000)


def test_stereo_is_downmixed_to_mono() -> None:
    audio = parse_wav(wav_bytes(pcm16(100, 300, -200, -400), channels=2))
    assert audio.pcm == pcm16(200, -300)


def test_float32_is_converted_to_pcm16() -> None:
    samples = np.array([0.5, -0.25, 2.0], dtype="<f4").tobytes()
    audio = parse_wav(wav_bytes(samples, bits=32, tag=3))
    assert audio.pcm == pcm16(16384, -8192, 32767)


def test_extensible_header_is_understood() -> None:
    audio = parse_wav(wav_bytes(pcm16(5, 6), extensible=True))
    assert audio.pcm == pcm16(5, 6)


def test_odd_trailing_byte_is_ignored() -> None:
    audio = parse_wav(wav_bytes(pcm16(7, 8) + b"\x01"))
    assert audio.pcm == pcm16(7, 8)


def test_extra_chunks_are_skipped() -> None:
    wav = wav_bytes(pcm16(1, 2))
    extra = b"LIST" + struct.pack("<I", 3) + b"abc" + b"\x00"  # odd size: padded to even
    riff_body = wav[8:] + extra
    wav = b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body
    assert parse_wav(wav).pcm == pcm16(1, 2)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"not a wav file at all", "RIFF/WAVE"),
        (b"RIFF\x00\x00\x00\x00WAVE", "fmt/data"),
        (wav_bytes(pcm16(1), rate=4_000), "outside"),
        (wav_bytes(pcm16(1), rate=192_000), "outside"),
        (wav_bytes(b"\x00\x00\x00", bits=24), "PCM16 and float32"),
        (wav_bytes(pcm16(1), channels=0), "no channel"),
    ],
)
def test_invalid_files_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(ApiError, match=message):
        parse_wav(data)

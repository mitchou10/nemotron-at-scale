"""Load test: N concurrent real-time audio streams, to find how many one instance can hold.

Run from `backend/`:

    uv run python scripts/bench_asr.py nemo 172.21.0.4:8080 -n 1,4,8,16
    uv run python scripts/bench_asr.py vosk 172.21.0.5:2700 -n 1,8,16,32
    uv run python scripts/bench_asr.py gateway localhost:8000 -n 4,16      # whole backend

Modes: `nemo` / `vosk` talk straight to one instance (find its real capacity, then set
`ASR_MAX_STREAMS_PER_INSTANCE` or the `#N` of its URL below the knee); `gateway` goes through
the backend WebSocket, so it also measures routing and failover overhead.

Each stream sends the audio at real-time speed (one chunk every `--chunk-ms`). Reported per N:
- first_result: delay before the first transcript (partial or final)
- final_lag: delay between the end of the audio and the final transcript
An instance keeps up while final_lag stays around 1 s or less; when it climbs, the instance
falls behind real time and N is over its capacity. Streams are real-time, so keep the test
machine otherwise idle (results include CPU contention from anything else running).
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
import wave
from pathlib import Path

from websockets.asyncio.client import connect

from app.services.nemo_speech import NemoSpeechTranscriber
from app.services.transcription import InstanceClient
from app.services.vosk import VoskTranscriber

DEFAULT_AUDIO = Path(__file__).parent / "samples" / "jfk.wav"
BYTES_PER_SECOND = 16_000 * 2
FINAL_TIMEOUT_S = 120.0


def load_audio(path: Path) -> bytes:
    """Raw PCM 16 kHz mono 16-bit, from a .pcm/.raw file or a WAV in that format."""
    if path.suffix.lower() in (".pcm", ".raw"):
        return path.read_bytes()
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16_000, 1, 2):
            sys.exit(
                f"{path} must be 16 kHz mono 16-bit. Convert it with:\n"
                f"  ffmpeg -i {path} -ar 16000 -ac 1 -sample_fmt s16 out.wav"
            )
        return wav.readframes(wav.getnframes())


async def instance_stream(
    client: InstanceClient, audio: bytes, chunk: int, interval: float
) -> tuple[float, float]:
    session = await client.open_session()
    started = time.perf_counter()
    first: list[float] = []
    done = asyncio.Event()

    async def read() -> None:
        async for event in session.events():
            if event.type in ("partial", "final") and not first:
                first.append(time.perf_counter() - started)
            if event.type == "committed":
                done.set()
                return

    reader = asyncio.create_task(read())
    for offset in range(0, len(audio), chunk):
        await session.send_audio(audio[offset : offset + chunk])
        await asyncio.sleep(interval)
    audio_end = time.perf_counter()
    await session.end()
    await asyncio.wait_for(done.wait(), FINAL_TIMEOUT_S)
    lag = time.perf_counter() - audio_end
    await reader
    await session.close()
    return (first[0] if first else float("nan")), lag


async def gateway_stream(
    target: str, audio: bytes, chunk: int, interval: float
) -> tuple[float, float]:
    url = f"ws://{target}/api/v1/ws/audio/bench-{uuid.uuid4().hex[:8]}"
    async with connect(url, max_size=None) as ws:
        started = time.perf_counter()
        first: list[float] = []
        audio_end = 0.0

        async def send() -> None:
            nonlocal audio_end
            for offset in range(0, len(audio), chunk):
                await ws.send(audio[offset : offset + chunk])
                await asyncio.sleep(interval)
            audio_end = time.perf_counter()
            await ws.send("end")

        sender = asyncio.create_task(send())
        try:
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), FINAL_TIMEOUT_S))
                if not first:
                    first.append(time.perf_counter() - started)
                if message["type"] == "final" and audio_end:
                    return first[0], time.perf_counter() - audio_end
        finally:
            await sender


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


async def run(args: argparse.Namespace, audio: bytes, n: int) -> None:
    chunk = BYTES_PER_SECOND * args.chunk_ms // 1000
    interval = args.chunk_ms / 1000

    def stream() -> asyncio.Future[tuple[float, float]] | object:
        if args.mode == "gateway":
            return gateway_stream(args.target, audio, chunk, interval)
        client: InstanceClient = (
            NemoSpeechTranscriber(f"ws://{args.target}/v1/audio/transcriptions/realtime")
            if args.mode == "nemo"
            else VoskTranscriber(f"ws://{args.target}")
        )
        return instance_stream(client, audio, chunk, interval)

    started = time.perf_counter()
    results = await asyncio.gather(*(stream() for _ in range(n)), return_exceptions=True)  # type: ignore[arg-type]
    ok = [r for r in results if not isinstance(r, BaseException)]
    firsts = [r[0] for r in ok]
    lags = [r[1] for r in ok]
    print(
        f"{args.mode:>7} N={n:>4} ok={len(ok):>4} err={len(results) - len(ok):>3} | "
        f"first_result p50={percentile(firsts, 0.5):5.2f}s p95={percentile(firsts, 0.95):5.2f}s | "
        f"final_lag p50={percentile(lags, 0.5):5.2f}s p95={percentile(lags, 0.95):5.2f}s "
        f"max={max(lags, default=float('nan')):5.2f}s | wall={time.perf_counter() - started:4.0f}s",
        flush=True,
    )
    if lags and statistics.median(lags) > args.max_lag:
        print(f"        -> median final_lag above {args.max_lag}s: N={n} is past capacity")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=["nemo", "vosk", "gateway"])
    parser.add_argument("target", help="host:port of the instance, or of the backend for gateway")
    parser.add_argument("-n", default="1,4,8,16", help="comma-separated stream counts to try")
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO, help="16 kHz mono WAV or .pcm")
    parser.add_argument("--seconds", type=float, help="use only the first N seconds of the audio")
    parser.add_argument("--chunk-ms", type=int, default=100)
    parser.add_argument("--max-lag", type=float, default=2.0, help="final_lag that counts as late")
    args = parser.parse_args()

    audio = load_audio(args.audio)
    if args.seconds:
        audio = audio[: int(args.seconds * BYTES_PER_SECOND)]
    print(f"audio: {len(audio) / BYTES_PER_SECOND:.1f}s per stream, chunks of {args.chunk_ms} ms")
    for n in (int(value) for value in args.n.split(",")):
        asyncio.run(run(args, audio, n))


if __name__ == "__main__":
    main()

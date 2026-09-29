"""Load test: how many real-time audio streams can one ASR instance hold, and with what delay?

Run from `backend/` (the audio sample is bundled):

    uv run python scripts/bench_asr.py vosk 172.21.0.5:2700 -n 1,8,16,32
    uv run python scripts/bench_asr.py vosk 172.21.0.5:2700 --find-capacity \
        --container nemotron-asr-vosk-2
    uv run python scripts/bench_asr.py nemo 172.21.0.4:8080 -n 1,4,8
    uv run python scripts/bench_asr.py gateway localhost:8000 -n 4,16       # whole backend

`vosk` / `nemo` talk straight to one instance; `gateway` goes through the backend WebSocket
(routing, buffering and failover included). Every stream sends the audio at real-time speed
(one chunk every `--chunk-ms`) and, for each N, the report gives:

- first_result: delay before the first transcript (partial or final)
- final_lag: delay between the end of the audio and the final transcript
- chunk_latency (vosk only): delay between sending each audio chunk and the server's reply.
  Above the chunk duration the instance is behind real time; `late` is the share of chunks
  in that case. This is the most precise load signal (also live in Prometheus as
  `asr_chunk_latency_seconds`).
- container (with --container NAME): peak CPU and memory seen by `docker stats`

N is "sustainable" when there is no error, p95 final_lag <= --max-lag and (vosk) late chunks
<= --max-late. `--find-capacity` doubles N until it fails, then bisects: the answer is the
largest sustainable N, the value to use as the instance limit (`#N` in ASR_URL). Keep the
machine otherwise idle: results include CPU contention from anything else running.
"""

import argparse
import asyncio
import json
import re
import sys
import time
import uuid
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

from websockets.asyncio.client import connect

from app.services.nemo_speech import NemoSpeechTranscriber
from app.services.transcription import InstanceClient
from app.services.vosk import VoskTranscriber

DEFAULT_AUDIO = Path(__file__).parent / "samples" / "jfk.wav"
BYTES_PER_SECOND = 16_000 * 2
FINAL_TIMEOUT_S = 120.0
NAN = float("nan")


@dataclass
class Stats:
    p50: float = NAN
    p90: float = NAN
    p95: float = NAN
    p99: float = NAN
    max: float = NAN

    @classmethod
    def of(cls, values: list[float]) -> "Stats":
        if not values:
            return cls()
        ordered = sorted(values)

        def at(q: float) -> float:
            return ordered[min(len(ordered) - 1, int(q * len(ordered)))]

        return cls(at(0.5), at(0.9), at(0.95), at(0.99), ordered[-1])

    def line(self, unit: str = "s", scale: float = 1.0) -> str:
        fields = (("p50", self.p50), ("p90", self.p90), ("p95", self.p95), ("p99", self.p99))
        text = "  ".join(f"{name} {value * scale:7.3f}" for name, value in fields)
        return f"{text}  max {self.max * scale:7.3f} {unit}"


@dataclass
class Run:
    n: int
    ok: int
    errors: int
    wall_s: float
    first_result: Stats
    final_lag: Stats
    chunk_latency: Stats | None = None
    chunks: int = 0
    late_pct: float | None = None
    cpu_peak_pct: float | None = None
    mem_peak_mib: float | None = None
    sustainable: bool = False
    reasons: list[str] = field(default_factory=list)


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
    return (first[0] if first else NAN), lag


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


def _mib(text: str) -> float:
    number, unit = re.match(r"([\d.]+)\s*([KMG]i?B)", text).groups()  # type: ignore[union-attr]
    return float(number) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "kB": 1 / 1024}.get(unit, 1)


async def watch_container(name: str, peaks: dict[str, float], stop: asyncio.Event) -> None:
    """Sample `docker stats` until stopped, keeping the peak CPU % and memory."""
    while not stop.is_set():
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}", name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            output, _ = await process.communicate()
            cpu, memory = output.decode().strip().split("|")
            peaks["cpu"] = max(peaks.get("cpu", 0.0), float(cpu.rstrip("%")))
            peaks["mem"] = max(peaks.get("mem", 0.0), _mib(memory.split("/")[0]))
        except (ValueError, OSError, AttributeError):
            await asyncio.sleep(1)


async def run_once(args: argparse.Namespace, audio: bytes, n: int) -> Run:
    chunk = BYTES_PER_SECOND * args.chunk_ms // 1000
    interval = args.chunk_ms / 1000
    latencies: list[float] = []

    def stream() -> object:
        if args.mode == "gateway":
            return gateway_stream(args.target, audio, chunk, interval)
        client: InstanceClient = (
            NemoSpeechTranscriber(f"ws://{args.target}/v1/audio/transcriptions/realtime")
            if args.mode == "nemo"
            else VoskTranscriber(f"ws://{args.target}", on_latency=latencies.append)
        )
        return instance_stream(client, audio, chunk, interval)

    peaks: dict[str, float] = {}
    stop = asyncio.Event()
    watcher = (
        asyncio.create_task(watch_container(args.container, peaks, stop))
        if args.container
        else None
    )
    started = time.perf_counter()
    results = await asyncio.gather(*(stream() for _ in range(n)), return_exceptions=True)  # type: ignore[arg-type]
    wall = time.perf_counter() - started
    stop.set()
    if watcher:
        await watcher

    ok = [r for r in results if not isinstance(r, BaseException)]
    run = Run(
        n=n,
        ok=len(ok),
        errors=len(results) - len(ok),
        wall_s=wall,
        first_result=Stats.of([r[0] for r in ok]),
        final_lag=Stats.of([r[1] for r in ok]),
        cpu_peak_pct=peaks.get("cpu"),
        mem_peak_mib=peaks.get("mem"),
    )
    if latencies:
        limit = args.chunk_ms / 1000
        run.chunk_latency = Stats.of(latencies)
        run.chunks = len(latencies)
        run.late_pct = 100 * sum(value > limit for value in latencies) / len(latencies)

    if run.errors:
        run.reasons.append(f"{run.errors} stream(s) failed")
    if run.final_lag.p95 > args.max_lag or run.ok == 0:
        run.reasons.append(f"p95 final_lag {run.final_lag.p95:.2f}s > {args.max_lag}s")
    if run.late_pct is not None and run.late_pct > args.max_late:
        run.reasons.append(f"{run.late_pct:.1f}% late chunks > {args.max_late}%")
    run.sustainable = not run.reasons
    return run


def show(run: Run, args: argparse.Namespace) -> None:
    verdict = "sustainable" if run.sustainable else "PAST CAPACITY: " + "; ".join(run.reasons)
    print(f"\nN={run.n}  streams ok {run.ok}/{run.n}  wall {run.wall_s:.0f}s  -> {verdict}")
    print(f"  first_result   {run.first_result.line()}")
    print(f"  final_lag      {run.final_lag.line()}")
    if run.chunk_latency:
        print(f"  chunk_latency  {run.chunk_latency.line('ms', 1000)}")
        print(
            f"  late chunks    {run.late_pct:.1f}% of {run.chunks} "
            f"(reply slower than {args.chunk_ms} ms)"
        )
    if run.cpu_peak_pct is not None:
        print(
            f"  container      cpu peak {run.cpu_peak_pct:.0f}%  "
            f"mem peak {run.mem_peak_mib:.0f} MiB"
        )


async def find_capacity(args: argparse.Namespace, audio: bytes) -> tuple[int, list[Run]]:
    runs: list[Run] = []

    async def attempt(n: int) -> bool:
        run = await run_once(args, audio, n)
        show(run, args)
        runs.append(run)
        return run.sustainable

    good, n, bad = 0, 1, None
    while n <= args.max_n:
        if await attempt(n):
            good, n = n, n * 2
        else:
            bad = n
            break
    while bad is not None and bad - good > 1:
        middle = (good + bad) // 2
        if await attempt(middle):
            good = middle
        else:
            bad = middle
    return good, runs


def summary(runs: list[Run]) -> None:
    print(
        "\n  N   ok  first_p95  lag_p50  lag_p95  lag_max  chunk_p95  chunk_p99   late   cpu%   mem"
    )
    for run in sorted(runs, key=lambda r: r.n):
        chunk = run.chunk_latency
        print(
            f"{run.n:>3} {run.ok:>4}  {run.first_result.p95:8.2f}s {run.final_lag.p50:7.2f}s "
            f"{run.final_lag.p95:7.2f}s {run.final_lag.max:7.2f}s  "
            + (
                f"{chunk.p95 * 1000:7.0f}ms {chunk.p99 * 1000:8.0f}ms {run.late_pct:5.1f}%"
                if chunk and run.late_pct is not None
                else f"{'-':>9} {'-':>10} {'-':>6}"
            )
            + (f"  {run.cpu_peak_pct:5.0f}" if run.cpu_peak_pct is not None else "      -")
            + (f"  {run.mem_peak_mib / 1024:4.1f}G" if run.mem_peak_mib is not None else "     -")
            + ("" if run.sustainable else "   <- past capacity")
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=["nemo", "vosk", "gateway"])
    parser.add_argument("target", help="host:port of the instance, or of the backend for gateway")
    parser.add_argument("-n", default="1,4,8,16", help="comma-separated stream counts to try")
    parser.add_argument("--find-capacity", action="store_true", help="search the largest N")
    parser.add_argument("--max-n", type=int, default=128, help="upper bound for --find-capacity")
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO, help="16 kHz mono WAV or .pcm")
    parser.add_argument("--seconds", type=float, help="use only the first N seconds of the audio")
    parser.add_argument("--chunk-ms", type=int, default=100)
    parser.add_argument("--max-lag", type=float, default=2.0, help="max p95 final_lag (s)")
    parser.add_argument("--max-late", type=float, default=5.0, help="max %% of late chunks (vosk)")
    parser.add_argument("--container", help="docker container to watch (peak CPU / memory)")
    parser.add_argument("--json", type=Path, help="also write every run as JSON")
    args = parser.parse_args()

    audio = load_audio(args.audio)
    if args.seconds:
        audio = audio[: int(args.seconds * BYTES_PER_SECOND)]
    print(f"audio: {len(audio) / BYTES_PER_SECOND:.1f}s per stream, chunks of {args.chunk_ms} ms")

    async def run_all() -> list[Run]:
        if args.find_capacity:
            capacity, runs = await find_capacity(args, audio)
            summary(runs)
            print(f"\nCapacity: {capacity} concurrent stream(s) on this instance")
            return runs
        runs = []
        for n in (int(value) for value in args.n.split(",")):
            run = await run_once(args, audio, n)
            show(run, args)
            runs.append(run)
        summary(runs)
        return runs

    runs = asyncio.run(run_all())
    if args.json:
        args.json.write_text(json.dumps([asdict(run) for run in runs], indent=2))
        print(f"\nwritten: {args.json}")


if __name__ == "__main__":
    main()

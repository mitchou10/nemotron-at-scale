"""Fill the database with plausible history, to look at the admin interface.

    DATABASE_URL=postgresql+asyncpg://... uv run python scripts/seed_demo.py [--days 7]

Adds audio streams and text-to-speech calls spread over the last days (busier in the daytime, a
few failures). Nothing is registered: start real workers, or `PUT /api/v1/registry/instances/<id>`.
Development only: it never runs in the services.
"""

import argparse
import asyncio
import random
import uuid
from datetime import timedelta

from app.db import AsyncSessionLocal
from app.models.asr import AsrStream, TtsCall
from app.services.state import utcnow

VOICES = [("fr_FR-siwis-medium", 70), ("fr_FR-upmc-medium", 20), ("en_US-lessac-medium", 10)]
FORMATS = [("mp3", 65), ("wav", 20), ("pcm", 15)]
TTS_INSTANCES = ["tts-1", "tts-2"]  # registry ids, as the gateway logs them
ASR_INSTANCES = ["10.42.1.4:8080", "10.42.1.9:8080", "10.42.2.3:8080"]


def weighted(choices: list[tuple[str, int]]) -> str:
    return random.choices([c for c, _ in choices], [w for _, w in choices])[0]


def moment(days: int):  # type: ignore[no-untyped-def]
    """A time in the last `days`, more likely recent and in working hours."""
    while True:
        at = utcnow() - timedelta(seconds=random.random() ** 1.15 * days * 86400)
        hour = at.astimezone().hour
        if random.random() < (0.9 if 8 <= hour < 19 else 0.25):
            return at


def tts_call(days: int) -> TtsCall:
    roll = random.random()
    status = 200 if roll < 0.93 else 429 if roll < 0.955 else 400 if roll < 0.975 else 503
    ok = status == 200
    characters = int(random.lognormvariate(5.0, 0.8))
    duration = int(random.lognormvariate(5.9, 0.45)) + characters // 4
    return TtsCall(
        at=moment(days),
        status_code=status,
        instance=random.choice(TTS_INSTANCES) if status in (200, 429) else None,
        voice=weighted(VOICES) if ok else None,
        response_format=weighted(FORMATS),
        characters=characters,
        audio_bytes=characters * random.randint(900, 1500) if ok else 0,
        duration_ms=duration if ok else random.randint(2, 40),
        first_byte_ms=int(duration * random.uniform(0.12, 0.3)) if ok else None,
    )


def stream(days: int, *, running: bool = False) -> AsrStream:
    started = utcnow() - timedelta(seconds=random.randint(20, 600)) if running else moment(days)
    roll = random.random()
    status = (
        "running"
        if running
        else "ended"
        if roll < 0.9
        else "failed"
        if roll < 0.96
        else "interrupted"
    )
    duration = random.lognormvariate(4.3, 0.9)
    ended = None if running else started + timedelta(seconds=duration)
    return AsrStream(
        id=uuid.uuid4().hex,
        client_id=f"client-{random.randint(1, 60):04d}",
        instance=random.choice(ASR_INSTANCES),
        status=status,
        failovers=1 if status != "ended" and random.random() < 0.5 else 0,
        started_at=started,
        updated_at=ended or utcnow(),
        ended_at=ended,
    )


async def main(days: int, tts: int, streams: int) -> None:
    async with AsyncSessionLocal() as session:
        session.add_all([tts_call(days) for _ in range(tts)])
        session.add_all([stream(days) for _ in range(streams)])
        session.add_all([stream(days, running=True) for _ in range(3)])
        await session.commit()
    print(f"added {tts} text-to-speech calls and {streams + 3} audio streams over {days} days")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--tts", type=int, default=1800)
    parser.add_argument("--streams", type=int, default=420)
    args = parser.parse_args()
    asyncio.run(main(args.days, args.tts, args.streams))

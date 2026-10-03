"""Statistics for the admin interface: audio streams and text-to-speech calls over a period."""

import math
from collections import Counter
from datetime import datetime
from typing import Any

from app.services.calls import TtsCallRecord
from app.services.state import ACTIVE_STREAM_STATUSES, StreamState, StreamStatus


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _top(counter: Counter[str], key: str, limit: int = 8) -> list[dict[str, Any]]:
    return [{key: name, "count": count} for name, count in counter.most_common(limit)]


def stream_duration_s(stream: StreamState) -> float:
    end = stream.ended_at or stream.updated_at
    return max(0.0, (end - stream.started_at).total_seconds())


def stt_summary(streams: list[StreamState], *, active_now: int) -> dict[str, Any]:
    durations = [stream_duration_s(s) for s in streams if s.status not in ACTIVE_STREAM_STATUSES]
    by_status = Counter(str(s.status) for s in streams)
    return {
        "streams": len(streams),
        "active": active_now,
        "ended": by_status[str(StreamStatus.ENDED)],
        "failed": by_status[str(StreamStatus.FAILED)],
        "interrupted": by_status[str(StreamStatus.INTERRUPTED)],
        "failovers": sum(s.failovers for s in streams),
        "unique_clients": len({s.client_id for s in streams}),
        "total_duration_s": round(sum(durations), 1),
        "avg_duration_s": _mean(durations),
        "by_instance": _top(Counter(s.instance for s in streams), "instance"),
    }


def tts_summary(calls: list[TtsCallRecord]) -> dict[str, Any]:
    ok = [c for c in calls if c.status_code < 400]
    durations = [float(c.duration_ms) for c in ok]
    first_bytes = [float(c.first_byte_ms) for c in ok if c.first_byte_ms is not None]
    total = len(calls)

    def rounded(value: float | None) -> float | None:
        return None if value is None else round(value, 1)

    return {
        "requests": total,
        "ok": len(ok),
        "client_errors": sum(400 <= c.status_code < 500 and c.status_code != 429 for c in calls),
        "rate_limited": sum(c.status_code == 429 for c in calls),
        "server_errors": sum(c.status_code >= 500 for c in calls),
        "success_rate_pct": round(100 * len(ok) / total, 1) if total else None,
        "characters": sum(c.characters for c in calls),
        "audio_bytes": sum(c.audio_bytes for c in ok),
        "avg_duration_ms": _mean(durations),
        "p50_duration_ms": rounded(percentile(durations, 50)),
        "p95_duration_ms": rounded(percentile(durations, 95)),
        "avg_first_byte_ms": _mean(first_bytes),
        "p95_first_byte_ms": rounded(percentile(first_bytes, 95)),
        "by_voice": _top(Counter(c.voice for c in ok if c.voice), "voice"),
        "by_format": _top(Counter(c.response_format for c in ok if c.response_format), "format"),
        "by_instance": _top(Counter(c.instance for c in ok if c.instance), "instance"),
    }


def timeseries(
    streams: list[StreamState],
    calls: list[TtsCallRecord],
    *,
    since: datetime,
    until: datetime,
    buckets: int,
) -> dict[str, Any]:
    """Calls per time slice: streams started, and TTS requests (ok / failed) with their latency."""
    width = (until - since) / buckets
    rows: list[dict[str, Any]] = [
        {
            "start": (since + width * n).isoformat(),
            "stt_streams": 0,
            "stt_failed": 0,
            "tts_ok": 0,
            "tts_failed": 0,
            "tts_characters": 0,
            "_durations": [],
        }
        for n in range(buckets)
    ]

    def slot(moment: datetime) -> int | None:
        index = int((moment - since) / width)
        return min(buckets - 1, index) if index >= 0 else None

    for stream in streams:
        if (i := slot(stream.started_at)) is not None:
            rows[i]["stt_streams"] += 1
            rows[i]["stt_failed"] += stream.status == StreamStatus.FAILED
    for call in calls:
        if (i := slot(call.at)) is None:
            continue
        if call.status_code < 400:
            rows[i]["tts_ok"] += 1
            rows[i]["tts_characters"] += call.characters
            rows[i]["_durations"].append(float(call.duration_ms))
        else:
            rows[i]["tts_failed"] += 1
    for row in rows:
        row["tts_avg_duration_ms"] = _mean(row.pop("_durations"))
    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "bucket_seconds": round(width.total_seconds()),
        "buckets": rows,
    }

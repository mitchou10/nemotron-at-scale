"""Status page history: instance samples and streams folded into fixed-size time buckets."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.services.state import ACTIVE_STREAM_STATUSES, InstanceSample, StreamState, StreamStatus


@dataclass
class _Bucket:
    samples: int = 0
    up: int = 0
    latency_sum: float = 0.0
    latency_count: int = 0
    max_active: int = 0


def summarize(
    samples: list[InstanceSample],
    streams: list[StreamState],
    *,
    since: datetime,
    until: datetime,
    buckets: int,
) -> dict[str, Any]:
    """Per-instance uptime, latency and load over [since, until], plus stream totals."""
    width = (until - since) / buckets
    per_instance: dict[str, list[_Bucket]] = defaultdict(
        lambda: [_Bucket() for _ in range(buckets)]
    )
    capacity: dict[str, int] = {}

    for sample in samples:
        index = min(buckets - 1, int((sample.at - since) / width))
        if index < 0:
            continue
        bucket = per_instance[sample.instance][index]
        bucket.samples += 1
        bucket.up += sample.up
        bucket.max_active = max(bucket.max_active, sample.active_streams)
        if sample.up and sample.latency_ms is not None:
            bucket.latency_sum += sample.latency_ms
            bucket.latency_count += 1
        capacity[sample.instance] = sample.max_streams

    instances = []
    for key in sorted(per_instance):
        rows = per_instance[key]
        total = sum(b.samples for b in rows)
        latency_count = sum(b.latency_count for b in rows)
        instances.append(
            {
                "instance": key,
                "max_streams": capacity.get(key),
                "uptime_pct": round(100 * sum(b.up for b in rows) / total, 2) if total else None,
                "avg_latency_ms": round(sum(b.latency_sum for b in rows) / latency_count, 1)
                if latency_count
                else None,
                "peak_streams": max(b.max_active for b in rows),
                "buckets": [_bucket_json(b, since + width * n, width) for n, b in enumerate(rows)],
            }
        )

    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "bucket_seconds": round(width.total_seconds()),
        "instances": instances,
        "streams": _stream_totals(streams),
    }


def _bucket_json(bucket: _Bucket, start: datetime, width: timedelta) -> dict[str, Any]:
    return {
        "start": start.isoformat(),
        "samples": bucket.samples,
        "up_ratio": round(bucket.up / bucket.samples, 3) if bucket.samples else None,
        "avg_latency_ms": round(bucket.latency_sum / bucket.latency_count, 1)
        if bucket.latency_count
        else None,
        "max_active_streams": bucket.max_active,
    }


def _stream_totals(streams: list[StreamState]) -> dict[str, int]:
    return {
        "started": len(streams),
        "active": sum(s.status in ACTIVE_STREAM_STATUSES for s in streams),
        "ended": sum(s.status == StreamStatus.ENDED for s in streams),
        "failed": sum(s.status == StreamStatus.FAILED for s in streams),
        "interrupted": sum(s.status == StreamStatus.INTERRUPTED for s in streams),
        "failovers": sum(s.failovers for s in streams),
    }

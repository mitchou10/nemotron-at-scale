"""Prometheus metrics of the service."""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, ProcessCollector

CHUNK_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)


class Metrics:
    def __init__(self, max_streams: int) -> None:
        self.registry = CollectorRegistry()
        r = self.registry
        self.active = Gauge("vosk_active_streams", "Realtime streams in progress", registry=r)
        self.capacity = Gauge("vosk_max_streams", "Realtime stream limit", registry=r)
        self.capacity.set(max_streams)
        self.streams = Counter("vosk_streams_total", "Realtime streams accepted", registry=r)
        self.rejected = Counter(
            "vosk_streams_rejected_total", "Realtime streams refused at capacity", registry=r
        )
        self.idle_closed = Counter(
            "vosk_streams_closed_idle_total", "Streams closed for inactivity", registry=r
        )
        self.chunk_seconds = Histogram(
            "vosk_chunk_seconds",
            "Decoding time of one audio chunk (above the chunk duration, streams fall behind)",
            buckets=CHUNK_BUCKETS,
            registry=r,
        )
        self.audio_seconds = Counter(
            "vosk_audio_seconds_total", "Seconds of audio decoded", registry=r
        )
        self.requests = Counter(
            "vosk_transcription_requests_total",
            "POST /v1/audio/transcriptions requests (ok, error or rejected at capacity)",
            ["status"],
            registry=r,
        )
        ProcessCollector(registry=r)

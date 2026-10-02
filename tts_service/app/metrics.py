"""Prometheus metrics of the service."""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, ProcessCollector

SYNTHESIS_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


class Metrics:
    def __init__(self, max_requests: int) -> None:
        self.registry = CollectorRegistry()
        r = self.registry
        self.active = Gauge("tts_active_requests", "Syntheses in progress", registry=r)
        self.capacity = Gauge("tts_max_requests", "Synthesis limit", registry=r)
        self.capacity.set(max_requests)
        self.requests = Counter(
            "tts_speech_requests_total",
            "POST /v1/audio/speech requests (ok, error or rejected at capacity)",
            ["status"],
            registry=r,
        )
        self.characters = Counter(
            "tts_input_characters_total", "Characters of text synthesized", registry=r
        )
        self.audio_seconds = Counter(
            "tts_audio_seconds_total", "Seconds of audio produced", registry=r
        )
        self.first_audio_seconds = Histogram(
            "tts_first_audio_seconds",
            "Time from the request to the first audio chunk",
            buckets=SYNTHESIS_BUCKETS,
            registry=r,
        )
        self.synthesis_seconds = Histogram(
            "tts_synthesis_seconds",
            "Total synthesis time of a request",
            buckets=SYNTHESIS_BUCKETS,
            registry=r,
        )
        ProcessCollector(registry=r)

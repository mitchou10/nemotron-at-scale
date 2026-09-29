"""Prometheus metrics of the ASR gateway (per instance)."""

import contextlib
from collections.abc import Callable, Iterable

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, ProcessCollector
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

PROBE_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0)
RESULT_BUCKETS = (0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0, 5.0)

_INSTANCE = ["instance"]


class BufferCollector(Collector):
    """Audio bytes buffered for failover, per instance, computed at scrape time."""

    def __init__(self, usage: Callable[[], dict[str, int]]) -> None:
        self._usage = usage

    def collect(self) -> Iterable[GaugeMetricFamily]:
        family = GaugeMetricFamily(
            "asr_buffer_bytes",
            "Audio bytes buffered in memory for failover, by instance serving the streams",
            labels=["instance"],
        )
        for instance, size in sorted(self._usage().items()):
            family.add_metric([instance], size)
        yield family


class GatewayMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        r = self.registry
        self.up = Gauge("asr_instance_up", "1 if the instance is healthy", _INSTANCE, registry=r)
        self.latency = Gauge(
            "asr_instance_latency_ms", "Smoothed /ready latency in ms", _INSTANCE, registry=r
        )
        self.active = Gauge(
            "asr_instance_active_streams",
            "Streams currently on the instance",
            _INSTANCE,
            registry=r,
        )
        self.capacity = Gauge(
            "asr_instance_max_streams", "Stream limit of the instance", _INSTANCE, registry=r
        )
        self.probe_seconds = Histogram(
            "asr_instance_probe_seconds",
            "Latency of /ready probes",
            _INSTANCE,
            buckets=PROBE_BUCKETS,
            registry=r,
        )
        self.probe_failures = Counter(
            "asr_instance_probe_failures_total", "Failed /ready probes", _INSTANCE, registry=r
        )
        self.open_seconds = Histogram(
            "asr_session_open_seconds",
            "Time to open a WebSocket session on the instance",
            _INSTANCE,
            buckets=PROBE_BUCKETS,
            registry=r,
        )
        self.streams_opened = Counter(
            "asr_streams_opened_total", "Streams opened on the instance", _INSTANCE, registry=r
        )
        self.open_failures = Counter(
            "asr_stream_open_failures_total",
            "Failed attempts to open a stream on the instance",
            _INSTANCE,
            registry=r,
        )
        self.instance_failures = Counter(
            "asr_instance_failures_total",
            "Streams broken by the instance dropping",
            _INSTANCE,
            registry=r,
        )
        self.failovers = Counter(
            "asr_failovers_total",
            "Streams resumed on the instance after another one failed",
            _INSTANCE,
            registry=r,
        )
        self.first_result_seconds = Histogram(
            "asr_first_result_seconds",
            "Time from the first audio sent to the first transcript received",
            _INSTANCE,
            buckets=RESULT_BUCKETS,
            registry=r,
        )
        self.buffer_limit = Gauge(
            "asr_buffer_limit_bytes", "Maximum audio bytes buffered per stream", registry=r
        )
        ProcessCollector(registry=r)
        self.rejected = Counter(
            "asr_streams_rejected_total",
            "Streams the gateway could not place",
            ["reason"],
            registry=r,
        )

    def track_buffers(self, usage: Callable[[], dict[str, int]]) -> None:
        self.registry.register(BufferCollector(usage))

    def publish_instance(
        self, key: str, *, up: bool, latency_ms: float | None, active: int, max_streams: int
    ) -> None:
        self.up.labels(key).set(1 if up else 0)
        if latency_ms is not None:
            self.latency.labels(key).set(latency_ms)
        self.active.labels(key).set(active)
        self.capacity.labels(key).set(max_streams)

    def forget_instance(self, key: str) -> None:
        for gauge in (self.up, self.latency, self.active, self.capacity):
            with contextlib.suppress(KeyError):
                gauge.remove(key)

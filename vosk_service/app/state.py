"""Shared server state: the engine (loaded in the background), limits, metrics, workers."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.config import Settings
from app.engine import Engine
from app.errors import ApiError
from app.metrics import Metrics


class ServerState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.metrics = Metrics(settings.max_streams)
        self.executor = ThreadPoolExecutor(settings.threads, thread_name_prefix="vosk")
        self.engine: Engine | None = None
        self.load_error: str | None = None
        self.active_streams = 0
        self.active_requests = 0

    @property
    def ready(self) -> bool:
        return self.engine is not None

    def require_engine(self) -> Engine:
        if self.engine is None:
            detail = f": {self.load_error}" if self.load_error else ""
            raise ApiError(f"the model is not loaded{detail}", 503, "server_error")
        return self.engine

    def try_open_stream(self) -> bool:
        if self.at_capacity:
            self.metrics.rejected.inc()
            return False
        self.active_streams += 1
        self.metrics.active.set(self.active_streams)
        self.metrics.streams.inc()
        return True

    def try_open_request(self) -> bool:
        if self.active_requests >= self.settings.max_requests:
            self.metrics.requests.labels("rejected").inc()
            return False
        self.active_requests += 1
        return True

    def close_request(self) -> None:
        self.active_requests -= 1

    @property
    def at_capacity(self) -> bool:
        return self.active_streams >= self.settings.max_streams

    def close_stream(self) -> None:
        self.active_streams -= 1
        self.metrics.active.set(self.active_streams)

    async def run(self, function, *args):  # type: ignore[no-untyped-def]
        """Run CPU-bound decoding in the worker pool."""
        return await asyncio.get_running_loop().run_in_executor(self.executor, function, *args)

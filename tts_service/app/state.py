"""Shared server state: the engine (loaded in the background), limits, metrics, workers."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import Settings
from app.engine import Engine
from app.errors import ApiError
from app.metrics import Metrics


class ServerState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.metrics = Metrics(settings.max_requests)
        self.executor = ThreadPoolExecutor(settings.max_requests, thread_name_prefix="tts")
        self.engine: Engine | None = None
        self.load_error: str | None = None
        self.active_requests = 0

    @property
    def ready(self) -> bool:
        return self.engine is not None

    @property
    def at_capacity(self) -> bool:
        return self.active_requests >= self.settings.max_requests

    def require_engine(self) -> Engine:
        if self.engine is None:
            detail = f": {self.load_error}" if self.load_error else ""
            raise ApiError(f"the voices are not loaded{detail}", 503, "server_error")
        return self.engine

    def try_open_request(self) -> bool:
        if self.at_capacity:
            self.metrics.requests.labels("rejected").inc()
            return False
        self.active_requests += 1
        self.metrics.active.set(self.active_requests)
        return True

    def close_request(self) -> None:
        self.active_requests -= 1
        self.metrics.active.set(self.active_requests)

    async def run(self, function: Callable[..., Any], *args: Any) -> Any:
        """Run CPU-bound synthesis in the worker pool."""
        return await asyncio.get_running_loop().run_in_executor(self.executor, function, *args)

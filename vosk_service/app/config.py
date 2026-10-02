"""Settings, read from `VOSK_*` environment variables (or a .env file)."""

import math
import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CGROUP_ROOT = Path("/sys/fs/cgroup")


def cgroup_cpu_quota(root: Path = CGROUP_ROOT) -> float | None:
    """CPU limit of the container (e.g. Docker `--cpus`); None if unlimited."""
    try:  # cgroup v2: "<quota> <period>" or "max <period>"
        quota, period = (root / "cpu.max").read_text().split()
        return None if quota == "max" else int(quota) / int(period)
    except (OSError, ValueError):
        pass
    try:  # cgroup v1
        quota = int((root / "cpu" / "cpu.cfs_quota_us").read_text())
        period = int((root / "cpu" / "cpu.cfs_period_us").read_text())
        return None if quota < 0 else quota / period
    except (OSError, ValueError):
        return None


def available_cpus(root: Path = CGROUP_ROOT) -> float:
    """CPUs this process can really use: the allowed cores, capped by the container CPU limit.

    `os.cpu_count()` would report the host's cores inside a container, so a container limited to 1
    CPU on a 64-core node would size itself 64 times too big.
    """
    cores = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    quota = cgroup_cpu_quota(root)
    return min(float(cores or 1), quota) if quota else float(cores or 1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOSK_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # `VOSK_MAX_STREAMS=` (e.g. from a compose default) means unset
    )

    host: str = "0.0.0.0"
    port: int = 8080

    # Model: `model_name` is looked up in `model_dir`, and downloaded from `model_url` if missing.
    model_name: str = "vosk-model-small-fr-0.22"
    model_dir: str = "/models"
    model_url: str = "https://alphacephei.com/vosk/models/{name}.zip"

    # --- Limits (sized from the CPUs the container may use, see `available_cpus`) ---
    # Realtime streams accepted at once. Unset = streams_per_cpu x CPUs. Measured with the small
    # French model: capacity is about 4 streams per CPU, so 1.0 (default) is a safe margin;
    # raise it after measuring your model with backend/scripts/bench_asr.py.
    max_streams: int | None = Field(default=None, ge=1)
    streams_per_cpu: float = Field(default=1.0, gt=0)
    # Worker threads for decoding. Unset = CPUs (at least 1).
    threads: int | None = Field(default=None, ge=1)
    # POST /v1/audio/transcriptions running at once (429 beyond). Unset = threads.
    max_requests: int | None = Field(default=None, ge=1)
    max_upload_mb: int = Field(default=64, ge=1)  # per uploaded file
    max_stream_seconds: int = Field(default=3600, ge=1)  # per realtime stream
    idle_timeout_s: float = Field(default=120.0, ge=0)  # close a silent stream; 0 = never

    # Realtime: emit a final transcript each time Vosk detects the end of an utterance. Off by
    # default like nemo-speech: finals then come only from `input_audio_buffer.commit`.
    endpointing: bool = False

    # Registration in the backend (see app/registration.py). Without `registry_url` the server does
    # not register: whoever calls it must know its address.
    registry_url: str | None = None  # e.g. http://backend:8000
    registry_token: str | None = None
    registry_id: str | None = None  # unique per instance; default: the container hostname
    registry_priority: int = Field(default=0, ge=0, le=1000)  # fill order: lower first
    registry_interval_s: float = Field(default=10.0, gt=0)  # the backend's TTL is 30 s
    # Address the backend must use to reach this server. Default: the container IP and `port`.
    self_url: str | None = None  # e.g. http://asr-vosk:8080

    api_key: str | None = None
    cors_origin: str | None = None
    log_level: str = "info"

    @model_validator(mode="after")
    def _size_from_cpus(self) -> "Settings":
        cpus = available_cpus()
        if self.threads is None:
            self.threads = max(1, math.ceil(cpus))
        if self.max_streams is None:
            self.max_streams = max(1, math.floor(cpus * self.streams_per_cpu))
        if self.max_requests is None:
            self.max_requests = self.threads
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Settings, read from `TTS_*` environment variables (or a .env file)."""

import json
import os
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TTS_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    host: str = "0.0.0.0"
    port: int = 8080

    # Piper voices: names like `fr_FR-siwis-medium`, looked up in `voice_dir` and downloaded from
    # `voice_url` when missing. The first one is the default voice.
    voices: Annotated[list[str], NoDecode] = ["fr_FR-siwis-medium"]
    voice_dir: str = "/voices"
    voice_url: str = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

    # Syntheses running at once (429 beyond). Unset = CPUs. Each one uses a worker thread.
    max_requests: int = Field(default_factory=lambda: max(1, os.cpu_count() or 1), ge=1)
    max_input_chars: int = Field(default=4096, ge=1)  # same limit as OpenAI
    mp3_bitrate: int = Field(default=128, ge=32, le=320)  # kbit/s

    api_key: str | None = None
    cors_origin: str | None = None
    log_level: str = "info"

    @field_validator("voices", mode="before")
    @classmethod
    def _split_voices(cls, value: object) -> object:
        if isinstance(value, str):
            if value.lstrip().startswith("["):
                return json.loads(value)
            return [v.strip() for v in value.split(",") if v.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Application configuration using pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "nemotron-backend"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_LOG_LEVEL: str = "info"

    # Database (async driver: asyncpg)
    DATABASE_URL: str = "postgresql+asyncpg://nemotron:nemotron@db:5432/nemotron"
    DATABASE_URL_TEST: str = "postgresql+asyncpg://nemotron:nemotron@db:5432/nemotron_test"

    # Live transcription: URL of a `nemo-speech serve` realtime WebSocket
    ASR_ENABLED: bool = False
    # Comma-separated realtime WebSocket URLs, in fill order; each hostname is resolved to all
    # its IPs. Append `#N` to a URL to set its per-instance stream limit (default below).
    ASR_URL: str = (
        "ws://asr-gpu:8080/v1/audio/transcriptions/realtime,"
        "ws://asr-cpu:8080/v1/audio/transcriptions/realtime"
    )
    ASR_API_KEY: str | None = None
    ASR_DISCOVERY: Literal["dns", "static"] = "dns"
    ASR_STATE_STORE: Literal["database", "memory"] = "database"
    ASR_MAX_STREAMS_PER_INSTANCE: int = 8
    ASR_PROBE_INTERVAL_S: float = 5.0
    ASR_MAX_LATENCY_MS: float = 0.0  # 0 = never skip slow instances
    # Resume on another instance if one drops: audio kept per stream, and failover budget.
    ASR_BUFFER_SECONDS: int = 30
    ASR_MAX_FAILOVERS: int = 2

    # CORS
    CORS_ORIGINS: list[AnyHttpUrl] | list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()

"""Application configuration using pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
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

    # Live transcription: the gateway routes streams to the instances registered in the registry
    ASR_ENABLED: bool = False
    ASR_API_KEY: str | None = None
    ASR_STATE_STORE: Literal["database", "memory"] = "database"
    ASR_PROBE_INTERVAL_S: float = 5.0
    ASR_MAX_LATENCY_MS: float = 0.0  # 0 = never skip slow instances
    # Resume on another instance if one drops: audio kept per stream, and failover budget.
    ASR_BUFFER_SECONDS: int = 30
    ASR_MAX_FAILOVERS: int = 2
    # Status page history: one sample per instance every N seconds, kept for N hours (0 = off).
    ASR_HISTORY_INTERVAL_S: float = 30.0
    ASR_HISTORY_RETENTION_HOURS: int = 168

    # Text to speech: key sent to the registered `tts_service` instances, and the time a request
    # may take
    TTS_API_KEY: str | None = None
    TTS_TIMEOUT_S: float = 60.0

    # Registry: workers (transcription and text-to-speech servers) register themselves here.
    # Without a token the registry is open: set one outside local tests.
    REGISTRY_TOKEN: str | None = None
    # An instance whose last heartbeat is older than this is no longer routed to.
    REGISTRY_TTL_S: float = 30.0
    REGISTRY_STORE: Literal["database", "memory"] = "database"

    # CORS
    CORS_ORIGINS: list[AnyHttpUrl] | list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()

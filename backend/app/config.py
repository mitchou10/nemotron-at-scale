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
    DATABASE_URL_TEST: str = (
        "postgresql+asyncpg://nemotron:nemotron@db:5432/nemotron_test"
    )

    # CORS
    CORS_ORIGINS: list[AnyHttpUrl] | list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()

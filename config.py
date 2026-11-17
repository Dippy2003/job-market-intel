"""Central configuration loaded from environment variables / .env."""
from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings. Values come from the environment or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(..., description="PostgreSQL connection string")
    llm_api_key: str | None = None
    llm_model: str = "gemini-1.5-flash"
    scraper_user_agent: str = "job-market-intel/0.1 (student research project)"
    scraper_min_delay: float = Field(2.0, ge=2.0)
    scraper_max_delay: float = 4.0
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def use_psycopg3_driver(cls, v: str) -> str:
        """Make plain postgres URLs use the psycopg (v3) driver for SQLAlchemy."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v


@lru_cache
def get_settings() -> Settings:
    """Return cached settings (read .env once)."""
    return Settings()


def setup_logging(level: str | None = None) -> None:
    """Configure root logging once for scripts and the API."""
    logging.basicConfig(
        level=(level or get_settings().log_level).upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

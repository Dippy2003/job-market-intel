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
    # Call the LLM only when the matcher finds fewer skills than this. 0 disables it.
    llm_min_skills: int = Field(2, ge=0)
    scraper_user_agent: str = "job-market-intel/0.1 (student research project)"
    scraper_min_delay: float = Field(2.0, ge=2.0)
    scraper_max_delay: float = 4.0
    log_level: str = "INFO"
    # Comma-separated browser origins for the read-only API. "*" allows any origin.
    cors_origins: str = "*"

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def blank_llm_key_is_unset(cls, value: object) -> str | None:
        """Treat a blank LLM_API_KEY as unset so the fallback stays off."""
        if value is None:
            return None
        text = str(value).strip()
        return text or None

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

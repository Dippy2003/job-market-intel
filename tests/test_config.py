"""Tests for config loading (no real database needed)."""
from config import Settings


def test_database_url_gets_psycopg_driver(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db?sslmode=require")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+psycopg://u:p@host/db?sslmode=require"


def test_postgres_scheme_also_converted(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host/db")
    assert Settings(_env_file=None).database_url.startswith("postgresql+psycopg://")


def test_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.scraper_min_delay >= 2.0
    assert s.llm_api_key is None
    assert s.llm_model == "gemini-1.5-flash"
    assert s.llm_min_skills == 2


def test_blank_llm_key_is_unset(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    monkeypatch.setenv("LLM_API_KEY", "  ")
    assert Settings(_env_file=None).llm_api_key is None


def test_cors_origins_default_and_override(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings(_env_file=None).cors_origins == "*"
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, http://127.0.0.1:5173")
    assert Settings(_env_file=None).cors_origins == "http://localhost:3000, http://127.0.0.1:5173"

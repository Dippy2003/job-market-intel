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
    s = Settings(_env_file=None)
    assert s.scraper_min_delay >= 2.0
    assert s.llm_api_key is None

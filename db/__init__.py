"""PostgreSQL connection helpers (SQLAlchemy 2.x)."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import get_settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for ORM models."""


@lru_cache
def get_engine() -> Engine:
    """Create a single shared engine. pool_pre_ping handles Neon idle disconnects."""
    return create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a session that commits on success and rolls back on error."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection() -> str:
    """Run a trivial query and return the server version string."""
    with get_engine().connect() as conn:
        return conn.execute(text("SELECT version()")).scalar_one()


def _sql_statements(sql: str) -> list[str]:
    """Split a migration file into individual statements."""
    statements: list[str] = []
    for chunk in sql.split(";"):
        lines = [line for line in chunk.splitlines() if not line.strip().startswith("--")]
        statement = "\n".join(lines).strip()
        if statement:
            statements.append(statement)
    return statements


def apply_migrations() -> list[str]:
    """Apply new SQL files in db/migrations and record them in schema_migrations."""
    folder = Path(__file__).resolve().parent / "migrations"
    applied: list[str] = []
    with get_engine().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
        """))
        done = {row[0] for row in conn.execute(text("SELECT filename FROM schema_migrations"))}
        for path in sorted(folder.glob("*.sql")):
            if path.name in done:
                continue
            for statement in _sql_statements(path.read_text(encoding="utf-8")):
                conn.execute(text(statement))
            conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:filename)"),
                {"filename": path.name},
            )
            applied.append(path.name)
    return applied

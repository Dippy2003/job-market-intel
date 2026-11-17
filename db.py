"""PostgreSQL connection helpers (SQLAlchemy 2.x)."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import get_settings, setup_logging

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for ORM models (step 2)."""


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


if __name__ == "__main__":
    setup_logging()
    try:
        log.info("Connected: %s", check_connection())
    except Exception as exc:  # noqa: BLE001
        log.error("Database connection failed: %s", exc)
        raise SystemExit(1) from exc

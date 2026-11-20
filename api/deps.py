"""Database session for one API request."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from db import get_engine


def get_db() -> Iterator[Session]:
    """Yield a read-only session and close it when the request ends.

    The engine is built from ``config.get_settings().database_url``, which is
    ``DATABASE_URL`` from the environment or a local ``.env`` file.
    """
    session = Session(get_engine(), expire_on_commit=False)
    try:
        yield session
    finally:
        session.rollback()
        session.close()

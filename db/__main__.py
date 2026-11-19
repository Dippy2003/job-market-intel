"""Check the database connection: python -m db."""
from __future__ import annotations

import logging

from config import setup_logging
from db import apply_migrations, check_connection

log = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    try:
        log.info("Connected: %s", check_connection())
        new_files = apply_migrations()
        if new_files:
            log.info("Applied migrations: %s", ", ".join(new_files))
        else:
            log.info("No new migrations")
    except Exception as exc:  # noqa: BLE001
        log.error("Database connection failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

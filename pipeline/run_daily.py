"""One entry point: scrape ITPro, then clean and dedupe every job row."""
from __future__ import annotations

import argparse
import logging
from typing import Any

from sqlalchemy import text

from config import setup_logging
from db import get_engine
from pipeline.clean import clean_jobs
from pipeline.dedupe import dedupe_jobs
from scrapers.itpro import ItproScraper

log = logging.getLogger(__name__)


def job_count() -> int:
    with get_engine().connect() as conn:
        return conn.execute(text("SELECT count(*) FROM jobs")).scalar_one()


def run_daily(
    *,
    max_jobs: int | None = None,
    skip_scrape: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scrape new ITPro ads, then refresh normalized fields and duplicate flags."""
    setup_logging()
    before = job_count()
    summary: dict[str, Any] = {"jobs_before": before}

    if skip_scrape:
        summary["scrape"] = {"skipped": True}
    else:
        stats = ItproScraper(dry_run=dry_run).run(max_jobs=max_jobs)
        summary["scrape"] = stats
        log.info("Scrape finished: %s", stats)

    summary["clean"] = clean_jobs()
    summary["dedupe"] = dedupe_jobs()
    summary["jobs_after"] = job_count()
    summary["inserted_this_run"] = summary["jobs_after"] - before
    log.info(
        "Daily run done: %s jobs (+%s)",
        summary["jobs_after"],
        summary["inserted_this_run"],
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape ITPro, clean titles/locations, dedupe.")
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Stop after inserting this many new jobs (default: no limit)",
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Only run clean + dedupe on existing rows",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape without writing to the database",
    )
    args = parser.parse_args()
    print(run_daily(max_jobs=args.max_jobs, skip_scrape=args.skip_scrape, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
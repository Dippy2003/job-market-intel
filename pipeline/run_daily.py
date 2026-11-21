"""One entry point: scrape ITPro, topjobs.lk, XpressJobs, and Ikman IT, then clean and dedupe."""
from __future__ import annotations

import argparse
import logging
from typing import Any

from sqlalchemy import text

from config import setup_logging
from db import get_engine
from pipeline.clean import clean_jobs
from pipeline.dedupe import dedupe_jobs
from scrapers.ikman import IkmanScraper
from scrapers.itpro import ItproScraper
from scrapers.topjobs import TopjobsScraper
from scrapers.xpressjobs import XpressjobsScraper

log = logging.getLogger(__name__)

def scraper_classes() -> dict[str, type]:
    """Scraper classes in daily-run order."""
    return {
        "itpro": ItproScraper,
        "topjobs": TopjobsScraper,
        "xpressjobs": XpressjobsScraper,
        "ikman": IkmanScraper,
    }


def scraper_names(source: str) -> list[str]:
    """Return the scrapers to run. 'all' keeps the daily-run order."""
    available = scraper_classes()
    if source == "all":
        return list(available)
    if source not in available:
        known = ", ".join((*available, "all"))
        raise ValueError(f"Unknown source {source!r}. Choose {known}.")
    return [source]


def job_count() -> int:
    with get_engine().connect() as conn:
        return conn.execute(text("SELECT count(*) FROM jobs")).scalar_one()


def run_daily(
    *,
    max_jobs: int | None = None,
    skip_scrape: bool = False,
    dry_run: bool = False,
    source: str = "all",
) -> dict[str, Any]:
    """Scrape the selected sites, then refresh normalized fields and duplicate flags."""
    classes = scraper_classes()
    names = scraper_names(source)
    setup_logging()
    before = job_count()
    summary: dict[str, Any] = {"jobs_before": before, "source": source}

    if skip_scrape:
        summary["scrape"] = {"skipped": True}
    else:
        summary["scrape"] = {}
        for name in names:
            stats = classes[name](dry_run=dry_run).run(max_jobs=max_jobs)
            summary["scrape"][name] = stats
            log.info("Scrape finished for %s: %s", name, stats)

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape ITPro, topjobs.lk, XpressJobs, and Ikman IT, then clean and dedupe."
    )
    parser.add_argument(
        "--source",
        choices=[*scraper_classes(), "all"],
        default="all",
        help="Which site to scrape (default: all). Each selected site gets --max-jobs.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Stop each selected scraper after inserting this many new jobs (default: no limit)",
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print(
        run_daily(
            max_jobs=args.max_jobs,
            skip_scrape=args.skip_scrape,
            dry_run=args.dry_run,
            source=args.source,
        )
    )


if __name__ == "__main__":
    main()

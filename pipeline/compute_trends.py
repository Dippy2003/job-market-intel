"""Rebuild weekly skill demand, then forecast the next eight weeks.

Reads non-duplicate jobs, upserts ``skill_trends``, and upserts ``forecasts``.
Prints the skills with the most postings in the latest week.

    python -m pipeline.compute_trends
    python -m pipeline.compute_trends --top 15
    python -m pipeline.compute_trends --dry-run
"""
from __future__ import annotations

import argparse
import logging

from analytics.forecast import HORIZON, ForecastBuild, build_forecasts, sync_forecasts
from analytics.trends import TrendBuild, build_trends, fetch_demand_rows, sync_trends, top_skills
from config import setup_logging
from db import get_engine

log = logging.getLogger(__name__)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("--top must be a positive integer")
    return number


def render_report(ranking: list[dict[str, object]], forecast: ForecastBuild, *, dry_run: bool) -> str:
    """Text block the CLI prints: top skills, then how the forecasts were produced."""
    if ranking:
        week = ranking[0]["period_start"]
        lines = [f"Top skills for the week of {week.isoformat()}:"]
        for index, row in enumerate(ranking, start=1):
            lines.append(
                f"{index:>2}. {row['skill_name']}  count={row['count']}  share={row['share']:.6f}"
            )
    else:
        lines = ["No skill demand in the latest week."]
    lines.append(
        "Forecasts: "
        f"{forecast.prophet} prophet, "
        f"{forecast.fallback} linear fallback, "
        f"{forecast.skipped} skipped "
        f"(horizon {HORIZON} weeks)."
    )
    if dry_run:
        lines.append("Dry run: nothing was written.")
    return "\n".join(lines)


def compute_trends(*, dry_run: bool = False, top: int = 10) -> dict[str, object]:
    """Compute trends, forecast them, and write both unless ``dry_run`` is set."""
    if top < 1:
        raise ValueError("top must be a positive integer")
    engine = get_engine()
    with engine.connect() as conn:
        rows = fetch_demand_rows(conn)
    trends: TrendBuild = build_trends(rows)
    forecast = build_forecasts(trends.points, trends.latest)
    deleted_trends = 0
    deleted_forecasts = 0
    if not dry_run:
        with engine.begin() as conn:
            deleted_trends = sync_trends(conn, trends.points)
            deleted_forecasts = sync_forecasts(conn, forecast.points, origin=trends.latest)
    ranking = top_skills(trends, top)
    report = render_report(ranking, forecast, dry_run=dry_run)
    summary: dict[str, object] = {
        "dry_run": dry_run,
        "jobs": trends.jobs,
        "weeks": trends.weeks,
        "trend_rows": len(trends.points),
        "trends_deleted": deleted_trends,
        "forecast_rows": len(forecast.points),
        "forecasts_deleted": deleted_forecasts,
        "prophet": forecast.prophet,
        "fallback": forecast.fallback,
        "skipped": forecast.skipped,
        "top": ranking,
        "report": report,
    }
    log.info("Skill trends done: %s", {key: summary[key] for key in summary if key not in {"top", "report"}})
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute weekly skill demand and forecast the next 8 weeks.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute trends and forecasts and print the top skills without writing",
    )
    parser.add_argument(
        "--top",
        type=_positive_int,
        default=10,
        help="How many skills to print for the latest week (default: 10). Forecasts still cover every skill.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    setup_logging()
    result = compute_trends(dry_run=args.dry_run, top=args.top)
    print(result["report"])


if __name__ == "__main__":
    main()

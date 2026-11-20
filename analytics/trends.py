"""Weekly skill demand.

A job is dated by ``posted_date``. When that is missing, the date is the
calendar day of ``scraped_at`` in Sri Lanka (UTC+5:30, Asia/Colombo, no
daylight saving). Weeks start on Monday. ``count`` is how many
non-duplicate jobs mention the skill that week. ``share`` is that count
divided by every non-duplicate job dated to the same week, including jobs
with no skills. Shares are stored with six decimal places.

Duplicates (``jobs.duplicate_of``) are left out so the same posting on ITPro
and topjobs is not counted twice. Re-running upserts
``(skill_id, period_start)`` and deletes trend rows the current jobs no
longer support.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text

log = logging.getLogger(__name__)

# Sri Lanka has been UTC+5:30 year-round since 2006.
MARKET_TZ = timezone(timedelta(hours=5, minutes=30))
SHARE_QUANT = Decimal("0.000001")

FETCH_DEMAND_SQL = text("""
SELECT
    j.id AS job_id,
    j.posted_date AS posted_date,
    j.scraped_at AS scraped_at,
    js.skill_id AS skill_id,
    s.name AS skill_name
FROM jobs AS j
LEFT JOIN job_skills AS js ON js.job_id = j.id
LEFT JOIN skills AS s ON s.id = js.skill_id
WHERE j.duplicate_of IS NULL
ORDER BY j.id, js.skill_id
""")

SELECT_TRENDS_SQL = text("SELECT skill_id, period_start FROM skill_trends")

UPSERT_TREND_SQL = text("""
INSERT INTO skill_trends (skill_id, period_start, count, share)
VALUES (:skill_id, :period_start, :count, :share)
ON CONFLICT (skill_id, period_start) DO UPDATE
SET count = EXCLUDED.count,
    share = EXCLUDED.share
""")

DELETE_TREND_SQL = text("""
DELETE FROM skill_trends
WHERE skill_id = :skill_id AND period_start = :period_start
""")


@dataclass(frozen=True)
class DemandRow:
    """One job, optionally joined to one skill. ``skill_id`` is None when the job has none."""

    job_id: int
    posted_date: date | datetime | None
    scraped_at: date | datetime | None
    skill_id: int | None
    skill_name: str | None


@dataclass(frozen=True)
class TrendPoint:
    """One skill's demand for the week that starts on ``period_start`` (a Monday)."""

    skill_id: int
    period_start: date
    count: int
    share: Decimal


@dataclass(frozen=True)
class TrendBuild:
    """Trends computed from the current jobs, before anything is written."""

    points: list[TrendPoint]
    names: dict[int, str]
    jobs: int
    weeks: int
    latest: date | None


def _as_posted_date(value: date | datetime | None) -> date | None:
    """Use a posting date as a calendar day. Timestamps keep the date they already carry."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"posted_date must be a date, got {type(value).__name__}")


def _as_scraped_date(value: date | datetime | None) -> date | None:
    """Calendar day of a scrape. Aware timestamps are converted to Sri Lanka time."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None:
            value = value.astimezone(MARKET_TZ)
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"scraped_at must be a date, got {type(value).__name__}")


def effective_date(
    posted_date: date | datetime | None,
    scraped_at: date | datetime | None,
) -> date | None:
    """Prefer the posting date, and fall back to the scrape date."""
    posted = _as_posted_date(posted_date)
    if posted is not None:
        return posted
    return _as_scraped_date(scraped_at)


def week_start(day: date | datetime) -> date:
    """Monday of the week that contains ``day``."""
    if isinstance(day, datetime):
        day = day.date()
    return day - timedelta(days=day.weekday())


def _clean_name(name: str | None) -> str | None:
    if name is None:
        return None
    text_value = str(name).strip()
    return text_value or None


def _share(count: int, total: int) -> Decimal:
    return (Decimal(count) / Decimal(total)).quantize(SHARE_QUANT, rounding=ROUND_HALF_UP)


def build_trends(rows: Sequence[DemandRow]) -> TrendBuild:
    """Count weekly demand. The same job is counted once per skill and once in the denominator."""
    jobs_by_week: dict[date, set[int]] = {}
    skills_by_week: dict[date, dict[int, set[int]]] = {}
    names: dict[int, str] = {}
    dated_jobs: set[int] = set()

    for row in rows:
        day = effective_date(row.posted_date, row.scraped_at)
        if day is None:
            continue
        start = week_start(day)
        dated_jobs.add(row.job_id)
        jobs_by_week.setdefault(start, set()).add(row.job_id)
        if row.skill_id is None:
            continue
        skills_by_week.setdefault(start, {}).setdefault(row.skill_id, set()).add(row.job_id)
        if row.skill_id not in names:
            cleaned = _clean_name(row.skill_name)
            if cleaned is not None:
                names[row.skill_id] = cleaned

    points: list[TrendPoint] = []
    for start in sorted(skills_by_week):
        total = len(jobs_by_week.get(start, ()))
        if total < 1:
            continue
        for skill_id in sorted(skills_by_week[start]):
            count = len(skills_by_week[start][skill_id])
            if count < 1:
                continue
            points.append(
                TrendPoint(
                    skill_id=skill_id,
                    period_start=start,
                    count=count,
                    share=_share(count, total),
                )
            )
    latest = max(jobs_by_week) if jobs_by_week else None
    return TrendBuild(
        points=points,
        names=names,
        jobs=len(dated_jobs),
        weeks=len(jobs_by_week),
        latest=latest,
    )


def skill_label(names: dict[int, str], skill_id: int) -> str:
    """Name stored for a skill, or a stable placeholder when the join had none."""
    return names.get(skill_id, f"skill {skill_id}")


def top_skills(build: TrendBuild, top: int) -> list[dict[str, object]]:
    """Highest demand in the latest week that has any dated jobs."""
    if top < 1:
        raise ValueError("top must be a positive integer")
    if build.latest is None:
        return []
    rows = [point for point in build.points if point.period_start == build.latest]
    rows.sort(
        key=lambda point: (
            -point.count,
            -point.share,
            skill_label(build.names, point.skill_id),
            point.skill_id,
        )
    )
    ranking: list[dict[str, object]] = []
    for point in rows[:top]:
        ranking.append(
            {
                "skill_id": point.skill_id,
                "skill_name": skill_label(build.names, point.skill_id),
                "period_start": point.period_start,
                "count": point.count,
                "share": point.share,
            }
        )
    return ranking


def fetch_demand_rows(conn) -> list[DemandRow]:
    """Read non-duplicate jobs and their skills. One row per job/skill pair."""
    fetched = conn.execute(FETCH_DEMAND_SQL).all()
    rows: list[DemandRow] = []
    for row in fetched:
        skill_id = None if row.skill_id is None else int(row.skill_id)
        rows.append(
            DemandRow(
                job_id=int(row.job_id),
                posted_date=row.posted_date,
                scraped_at=row.scraped_at,
                skill_id=skill_id,
                skill_name=row.skill_name,
            )
        )
    return rows


def _coerce_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def sync_trends(conn, points: Sequence[TrendPoint]) -> int:
    """Upsert the new rows and delete trend keys that are no longer present. Returns deletions."""
    existing = conn.execute(SELECT_TRENDS_SQL).all()
    keep = {(point.skill_id, point.period_start) for point in points}
    removed = 0
    for row in existing:
        key = (int(row.skill_id), _coerce_date(row.period_start))
        if key in keep:
            continue
        conn.execute(DELETE_TREND_SQL, {"skill_id": key[0], "period_start": key[1]})
        removed += 1
    for point in points:
        conn.execute(
            UPSERT_TREND_SQL,
            {
                "skill_id": point.skill_id,
                "period_start": point.period_start,
                "count": point.count,
                "share": point.share,
            },
        )
    log.info("Skill trends: %s rows, %s stale rows removed", len(points), removed)
    return removed

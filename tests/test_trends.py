"""Weekly skill demand. In-memory rows only. No database and no network."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from analytics.trends import (
    FETCH_DEMAND_SQL,
    UPSERT_TREND_SQL,
    DemandRow,
    build_trends,
    effective_date,
    top_skills,
    week_start,
)

MONDAY = date(2026, 11, 9)
NEXT_MONDAY = date(2026, 11, 16)


def _row(job_id, posted, skill_id, name, scraped=None):
    return DemandRow(job_id, posted, scraped, skill_id, name)


def test_week_starts_on_monday():
    assert week_start(MONDAY) == MONDAY
    assert date(2026, 11, 15).strftime("%A") == "Sunday"
    assert week_start(date(2026, 11, 15)) == MONDAY
    assert week_start(NEXT_MONDAY) == NEXT_MONDAY


def test_posted_date_wins_and_scrape_falls_back_to_sri_lanka_time():
    scraped = datetime(2026, 11, 15, 20, 0, tzinfo=UTC)
    assert effective_date(date(2026, 11, 9), scraped) == date(2026, 11, 9)
    # 20:00 UTC is 01:30 the next morning in Asia/Colombo (UTC+5:30).
    assert effective_date(None, scraped) == NEXT_MONDAY
    assert effective_date(None, datetime(2026, 11, 15, 20, 0)) == date(2026, 11, 15)
    assert effective_date(None, None) is None


def test_weekly_counts_and_share_include_jobs_with_no_skills():
    rows = [
        _row(1, MONDAY, 10, "Python"),
        _row(1, MONDAY, 11, "SQL"),
        _row(2, date(2026, 11, 10), 10, "Python"),
        _row(3, date(2026, 11, 11), None, None),
        _row(4, NEXT_MONDAY, 10, "Python"),
        _row(5, date(2026, 11, 17), 12, "Go"),
        _row(6, NEXT_MONDAY, 10, "Python"),
    ]
    built = build_trends(rows)
    assert built.jobs == 6
    assert built.weeks == 2
    assert built.latest == NEXT_MONDAY
    by_key = {(point.skill_id, point.period_start): point for point in built.points}
    assert by_key[(10, MONDAY)].count == 2
    assert by_key[(10, MONDAY)].share == Decimal("0.666667")
    assert by_key[(11, MONDAY)].count == 1
    assert by_key[(11, MONDAY)].share == Decimal("0.333333")
    assert by_key[(10, NEXT_MONDAY)].count == 2
    assert by_key[(10, NEXT_MONDAY)].share == Decimal("0.666667")
    assert by_key[(12, NEXT_MONDAY)].share == Decimal("0.333333")
    assert built.names == {10: "Python", 11: "SQL", 12: "Go"}


def test_duplicate_skill_rows_count_once_and_blank_names_are_ignored():
    rows = [
        _row(1, MONDAY, 10, "Python"),
        _row(1, MONDAY, 10, "Python 3"),
        _row(2, MONDAY, 11, "   "),
    ]
    built = build_trends(rows)
    # Two jobs that week, so each skill is half of the postings. The repeated Python row counts once.
    assert [(point.skill_id, point.count, point.share) for point in built.points] == [
        (10, 1, Decimal("0.500000")),
        (11, 1, Decimal("0.500000")),
    ]
    assert built.jobs == 2
    assert built.names == {10: "Python"}
    ranking = top_skills(built, 10)
    assert [row["skill_name"] for row in ranking] == ["Python", "skill 11"]


def test_scraped_date_is_used_when_the_posting_has_no_date():
    scraped = datetime(2026, 11, 15, 20, 0, tzinfo=UTC)
    built = build_trends([_row(8, None, 10, "Python", scraped=scraped)])
    assert built.latest == NEXT_MONDAY
    assert built.points[0].period_start == NEXT_MONDAY
    assert built.points[0].count == 1


def test_rows_with_no_date_are_left_out():
    built = build_trends([_row(1, None, 10, "Python")])
    assert built.jobs == 0
    assert built.weeks == 0
    assert built.latest is None
    assert built.points == []
    assert top_skills(built, 5) == []


def test_top_skills_are_the_latest_week_only():
    rows = [
        _row(1, MONDAY, 10, "Python"),
        _row(2, MONDAY, 10, "Python"),
        _row(3, MONDAY, 10, "Python"),
        _row(4, NEXT_MONDAY, 11, "SQL"),
        _row(5, NEXT_MONDAY, 11, "SQL"),
        _row(6, NEXT_MONDAY, 12, "Go"),
    ]
    built = build_trends(rows)
    ranking = top_skills(built, 1)
    assert [(row["skill_name"], row["count"], row["period_start"]) for row in ranking] == [
        ("SQL", 2, NEXT_MONDAY)
    ]
    assert [row["skill_name"] for row in top_skills(built, 10)] == ["SQL", "Go"]


def test_equal_counts_break_ties_by_name():
    rows = [
        _row(1, NEXT_MONDAY, 11, "SQL"),
        _row(2, NEXT_MONDAY, 12, "Go"),
    ]
    ranking = top_skills(build_trends(rows), 10)
    assert [row["skill_name"] for row in ranking] == ["Go", "SQL"]


def test_upsert_targets_the_trend_primary_key_and_skips_duplicates():
    sql = str(UPSERT_TREND_SQL)
    fetch = str(FETCH_DEMAND_SQL)
    assert "INSERT INTO skill_trends (skill_id, period_start, count, share)" in sql
    assert "ON CONFLICT (skill_id, period_start)" in sql
    assert "duplicate_of IS NULL" in fetch
    assert "LEFT JOIN job_skills" in fetch
    assert "posted_date" in fetch
    assert "scraped_at" in fetch
    rebuilt = build_trends([_row(1, MONDAY + timedelta(days=1), 10, "Python")])
    assert rebuilt.points[0].period_start == MONDAY

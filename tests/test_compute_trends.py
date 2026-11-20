"""CLI wiring for trends and forecasts. The database is an in-memory fake."""
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from analytics.forecast import LINEAR_MODEL
from pipeline.compute_trends import build_parser, compute_trends

ROOT = Path(__file__).resolve().parents[1]
WEEK = date(2026, 11, 9)
NEXT = date(2026, 11, 16)
PAST_FORECAST = (10, date(2026, 11, 9), "prophet-weekly-1")
STALE_FUTURE = (10, date(2026, 11, 23), "prophet-weekly-1")


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Store:
    def __init__(self, jobs, trends=None, forecasts=None):
        self.jobs = jobs
        self.trends = list(trends or [])
        self.forecasts = list(forecasts or [])
        self.statements = []

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = dict(params or {})
        self.statements.append((sql, params))
        if "INSERT INTO skill_trends" in sql:
            key = (params["skill_id"], params["period_start"])
            self.trends = [row for row in self.trends if row != key]
            self.trends.append(key)
            return _Result([])
        if "DELETE FROM skill_trends" in sql:
            key = (params["skill_id"], params["period_start"])
            self.trends = [row for row in self.trends if row != key]
            return _Result([])
        if "FROM skill_trends" in sql:
            return _Result([_Row(skill_id=skill_id, period_start=start) for skill_id, start in self.trends])
        if "INSERT INTO forecasts" in sql:
            key = (params["skill_id"], params["ds"], params["model_version"])
            self.forecasts = [row for row in self.forecasts if row != key]
            self.forecasts.append(key)
            return _Result([])
        if "DELETE FROM forecasts" in sql:
            key = (params["skill_id"], params["ds"], params["model_version"])
            self.forecasts = [row for row in self.forecasts if row != key]
            return _Result([])
        if "FROM forecasts" in sql:
            rows = self.forecasts
            if "ds >" in sql:
                rows = [row for row in rows if row[1] > params["origin"]]
            return _Result(
                [_Row(skill_id=skill_id, ds=ds, model_version=version) for skill_id, ds, version in rows]
            )
        if "FROM jobs" in sql:
            return _Result(self.jobs)
        raise AssertionError(f"unexpected SQL: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Engine:
    def __init__(self, store):
        self.store = store
        self.began = 0
        self.connected = 0

    def begin(self):
        self.began += 1
        return self.store

    def connect(self):
        self.connected += 1
        return self.store


def _jobs():
    return [
        _Row(job_id=1, posted_date=WEEK, scraped_at=None, skill_id=10, skill_name="Python"),
        _Row(job_id=1, posted_date=WEEK, scraped_at=None, skill_id=11, skill_name="SQL"),
        _Row(job_id=2, posted_date=date(2026, 11, 10), scraped_at=None, skill_id=10, skill_name="Python"),
        _Row(job_id=3, posted_date=date(2026, 11, 11), scraped_at=None, skill_id=None, skill_name=None),
        _Row(job_id=4, posted_date=NEXT, scraped_at=None, skill_id=10, skill_name="Python"),
        _Row(job_id=5, posted_date=date(2026, 11, 17), scraped_at=None, skill_id=12, skill_name="Go"),
        _Row(job_id=6, posted_date=NEXT, scraped_at=None, skill_id=10, skill_name="Python"),
    ]


def _engine(monkeypatch, store):
    engine = _Engine(store)
    monkeypatch.setattr("pipeline.compute_trends.get_engine", lambda: engine)
    return engine


def test_dry_run_prints_the_latest_week_and_writes_nothing(monkeypatch):
    store = _Store(_jobs(), trends=[(99, date(2026, 1, 5))], forecasts=[STALE_FUTURE])
    engine = _engine(monkeypatch, store)
    summary = compute_trends(dry_run=True, top=10)
    assert engine.connected == 1
    assert engine.began == 0
    assert store.trends == [(99, date(2026, 1, 5))]
    assert store.forecasts == [STALE_FUTURE]
    assert not any("INSERT" in sql or "DELETE" in sql for sql, _params in store.statements)
    assert summary["dry_run"] is True
    assert summary["jobs"] == 6
    assert summary["weeks"] == 2
    assert summary["trend_rows"] == 4
    assert summary["forecast_rows"] == 16
    assert summary["prophet"] == 0
    assert summary["fallback"] == 2
    assert summary["skipped"] == 1
    assert [row["skill_name"] for row in summary["top"]] == ["Python", "Go"]
    assert summary["top"][0]["count"] == 2
    assert summary["top"][0]["share"] == Decimal("0.666667")
    assert summary["report"] == "\n".join(
        [
            "Top skills for the week of 2026-11-16:",
            " 1. Python  count=2  share=0.666667",
            " 2. Go  count=1  share=0.333333",
            "Forecasts: 0 prophet, 2 linear fallback, 1 skipped (horizon 8 weeks).",
            "Dry run: nothing was written.",
        ]
    )


def test_top_limits_the_printout_and_not_the_forecast(monkeypatch):
    store = _Store(_jobs())
    _engine(monkeypatch, store)
    summary = compute_trends(dry_run=True, top=1)
    assert [row["skill_name"] for row in summary["top"]] == ["Python"]
    assert "Go" not in summary["report"]
    assert summary["forecast_rows"] == 16
    assert summary["fallback"] == 2


def test_write_is_idempotent_and_replaces_stale_future_rows(monkeypatch):
    store = _Store(
        _jobs(),
        trends=[(99, date(2026, 1, 5))],
        forecasts=[PAST_FORECAST, STALE_FUTURE, (99, date(2026, 12, 7), LINEAR_MODEL)],
    )
    engine = _engine(monkeypatch, store)
    first = compute_trends(top=10)
    assert engine.began == 1
    assert first["trends_deleted"] == 1
    assert first["forecasts_deleted"] == 2
    assert set(store.trends) == {
        (10, WEEK),
        (11, WEEK),
        (10, NEXT),
        (12, NEXT),
    }
    assert PAST_FORECAST in store.forecasts
    assert STALE_FUTURE not in store.forecasts
    assert (99, date(2026, 12, 7), LINEAR_MODEL) not in store.forecasts
    future = [row for row in store.forecasts if row[1] > NEXT]
    assert len(future) == 16
    assert {row[2] for row in future} == {LINEAR_MODEL}
    assert (10, date(2026, 11, 23), LINEAR_MODEL) in future
    assert len(store.trends) == len(set(store.trends))
    assert len(store.forecasts) == len(set(store.forecasts))
    sql = "\n".join(statement for statement, _params in store.statements)
    assert "ON CONFLICT (skill_id, period_start)" in sql
    assert "ON CONFLICT (skill_id, ds, model_version)" in sql
    shares = {
        (params["skill_id"], params["period_start"]): (params["count"], params["share"])
        for statement, params in store.statements
        if "INSERT INTO skill_trends" in statement
    }
    assert shares[(10, WEEK)] == (2, Decimal("0.666667"))
    assert shares[(11, WEEK)] == (1, Decimal("0.333333"))

    before = (set(store.trends), set(store.forecasts))
    second = compute_trends(top=10)
    assert second["trends_deleted"] == 0
    assert second["forecasts_deleted"] == 0
    assert (set(store.trends), set(store.forecasts)) == before
    assert engine.began == 2


def test_empty_corpus_clears_derived_rows(monkeypatch):
    store = _Store([], trends=[(10, WEEK)], forecasts=[PAST_FORECAST])
    _engine(monkeypatch, store)
    summary = compute_trends()
    assert summary["jobs"] == 0
    assert summary["trend_rows"] == 0
    assert summary["forecast_rows"] == 0
    assert summary["trends_deleted"] == 1
    assert summary["forecasts_deleted"] == 1
    assert store.trends == []
    assert store.forecasts == []
    assert summary["report"].startswith("No skill demand in the latest week.")


def test_top_must_be_positive():
    with pytest.raises(ValueError):
        compute_trends(top=0)


def test_cli_help_and_flags():
    parser = build_parser()
    defaults = parser.parse_args([])
    assert defaults.dry_run is False
    assert defaults.top == 10
    selected = parser.parse_args(["--dry-run", "--top", "4"])
    assert selected.dry_run is True
    assert selected.top == 4
    with pytest.raises(SystemExit):
        parser.parse_args(["--top", "0"])
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.compute_trends", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout
    assert "--top" in result.stdout

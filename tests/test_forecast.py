"""Skill forecasts. Prophet is faked. No database, network, or Stan compile."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from analytics.forecast import (
    HORIZON,
    LINEAR_MODEL,
    MIN_PROPHET_WEEKS,
    PROPHET_MODEL,
    UPSERT_FORECAST_SQL,
    _predict_with_prophet,
    build_forecasts,
    fit_prophet,
    linear_forecast,
)
from analytics.trends import TrendPoint

ROOT = Path(__file__).resolve().parents[1]
START = date(2026, 1, 5)


def _weeks(skill_id, count, n, value=1):
    return [
        TrendPoint(
            skill_id,
            START + timedelta(days=7 * index),
            value if count is None else count[index],
            Decimal("0.100000"),
        )
        for index in range(n)
    ]


def _origin(n):
    return START + timedelta(days=7 * (n - 1))


def test_one_week_is_skipped_and_prophet_is_not_called():
    called = {"n": 0}

    def fit(history, horizon):
        called["n"] += 1
        return None

    result = build_forecasts(_weeks(1, [4], 1), _origin(1), fit=fit)
    assert result.points == []
    assert result.skipped == 1
    assert result.prophet == 0
    assert result.fallback == 0
    assert called["n"] == 0
    assert build_forecasts([], None, fit=fit).points == []


def test_two_week_line_matches_the_documented_band():
    result = build_forecasts(_weeks(1, [2, 4], 2), _origin(2))
    assert result.fallback == 1
    assert result.prophet == 0
    assert result.skipped == 0
    assert len(result.points) == HORIZON
    first, last = result.points[0], result.points[-1]
    assert first.model_version == LINEAR_MODEL
    assert first.ds == date(2026, 1, 19)
    assert (first.yhat, first.yhat_lower, first.yhat_upper) == (
        Decimal("6.0000"),
        Decimal("4.8000"),
        Decimal("7.2000"),
    )
    assert last.ds == date(2026, 3, 9)
    assert (last.yhat, last.yhat_lower, last.yhat_upper) == (
        Decimal("20.0000"),
        Decimal("16.0000"),
        Decimal("24.0000"),
    )
    assert all(point.yhat_lower <= point.yhat <= point.yhat_upper for point in result.points)


def test_flat_history_keeps_a_small_band_and_a_decline_stays_non_negative():
    flat = build_forecasts(_weeks(1, [4, 4, 4], 3), _origin(3))
    assert flat.fallback == 1
    assert (flat.points[0].yhat, flat.points[0].yhat_lower, flat.points[0].yhat_upper) == (
        Decimal("4.0000"),
        Decimal("3.8000"),
        Decimal("4.2000"),
    )
    declined = build_forecasts(_weeks(1, [5], 1), _origin(2))
    assert declined.fallback == 1
    assert all(point.yhat == Decimal("0.0000") for point in declined.points)
    assert all(point.yhat_lower <= point.yhat <= point.yhat_upper for point in declined.points)
    assert all(point.yhat_lower >= 0 for point in declined.points)


def test_gaps_are_zero_filled_through_the_latest_week_and_a_new_skill_is_skipped():
    seen = []

    def spy(history, horizon):
        seen.append(list(history))
        last = history[-1][0]
        return [(last + timedelta(days=7), 1.0, 0.5, 1.5)]

    early = TrendPoint(1, START, 5, Decimal("0.100000"))
    span = _weeks(2, None, MIN_PROPHET_WEEKS, value=1)
    latest_only = TrendPoint(3, _origin(MIN_PROPHET_WEEKS), 2, Decimal("0.100000"))
    result = build_forecasts([early, *span, latest_only], _origin(MIN_PROPHET_WEEKS), fit=spy)
    assert result.prophet == 2
    assert result.skipped == 1
    assert {point.skill_id for point in result.points} == {1, 2}
    histories = {history[0][1]: history for history in seen}
    assert len(histories[5.0]) == MIN_PROPHET_WEEKS
    assert histories[5.0][1] == (START + timedelta(days=7), 0.0)
    assert histories[5.0][-1][1] == 0.0
    assert all(point.model_version == PROPHET_MODEL for point in result.points)
    assert result.points[0].yhat == Decimal("1.0000")


def test_prophet_failure_uses_the_linear_fallback():
    def boom(history, horizon):
        raise RuntimeError("stan")

    failed = build_forecasts(
        _weeks(1, None, MIN_PROPHET_WEEKS, value=2),
        _origin(MIN_PROPHET_WEEKS),
        fit=boom,
    )
    assert failed.prophet == 0
    assert failed.fallback == 1
    assert failed.points[0].model_version == LINEAR_MODEL
    assert len(failed.points) == HORIZON

    missing = build_forecasts(
        _weeks(1, None, MIN_PROPHET_WEEKS, value=2),
        _origin(MIN_PROPHET_WEEKS),
        fit=lambda history, horizon: None,
    )
    assert missing.fallback == 1
    assert missing.points[0].model_version == LINEAR_MODEL


def test_negative_prophet_counts_are_clipped_at_zero():
    def negative(history, horizon):
        last = history[-1][0]
        return [(last + timedelta(days=7), -1.0, -2.0, 1.25)]

    result = build_forecasts(_weeks(1, None, MIN_PROPHET_WEEKS), _origin(MIN_PROPHET_WEEKS), fit=negative)
    point = result.points[0]
    assert result.prophet == 1
    assert (point.yhat, point.yhat_lower, point.yhat_upper) == (
        Decimal("0.0000"),
        Decimal("0.0000"),
        Decimal("1.2500"),
    )


def test_linear_forecast_rejects_a_single_point():
    with pytest.raises(ValueError):
        linear_forecast([(START, 1.0)], HORIZON)


def test_missing_prophet_or_a_failed_fit_returns_none(monkeypatch):
    def missing():
        raise ImportError("no prophet")

    monkeypatch.setattr("analytics.forecast._load_prophet", missing)
    history = [(START + timedelta(days=7 * index), float(index + 1)) for index in range(MIN_PROPHET_WEEKS)]
    assert fit_prophet(history, HORIZON) is None

    class Boom:
        def __init__(self, **kwargs):
            raise RuntimeError("stan")

    monkeypatch.setattr("analytics.forecast._load_prophet", lambda: Boom)
    assert fit_prophet(history, HORIZON) is None


def test_prophet_is_called_with_weekly_dates_and_no_seasonality(monkeypatch):
    pandas = pytest.importorskip("pandas")
    captured = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def fit(self, frame):
            captured["frame"] = frame

        def make_future_dataframe(self, periods, freq, include_history):
            captured["periods"] = periods
            captured["freq"] = freq
            captured["include_history"] = include_history
            start = datetime(2026, 3, 2)
            return pandas.DataFrame({"ds": [start + timedelta(days=7 * index) for index in range(periods)]})

        def predict(self, future):
            history = pandas.DataFrame(
                {
                    "ds": [datetime(2026, 1, 5)],
                    "yhat": [9.0],
                    "yhat_lower": [8.0],
                    "yhat_upper": [10.0],
                }
            )
            out = future.copy()
            out["yhat"] = 2.5
            out["yhat_lower"] = 2.0
            out["yhat_upper"] = 3.0
            return pandas.concat([history, out], ignore_index=True)

    monkeypatch.setattr("analytics.forecast._load_prophet", lambda: FakeModel)
    history = [(START + timedelta(days=7 * index), float(index + 1)) for index in range(MIN_PROPHET_WEEKS)]
    raw = fit_prophet(history, HORIZON)
    assert captured["kwargs"]["yearly_seasonality"] is False
    assert captured["kwargs"]["weekly_seasonality"] is False
    assert captured["kwargs"]["daily_seasonality"] is False
    assert captured["kwargs"]["growth"] == "linear"
    assert captured["kwargs"]["interval_width"] == 0.8
    assert list(captured["frame"]["y"]) == [float(index + 1) for index in range(MIN_PROPHET_WEEKS)]
    assert captured["periods"] == HORIZON
    assert captured["freq"] == "W-MON"
    assert captured["include_history"] is False
    assert raw is not None
    assert len(raw) == HORIZON
    assert raw[0][0] == date(2026, 3, 2)
    assert all(ds > history[-1][0] for ds, *_rest in raw)
    # The direct predictor is what fit_prophet delegates to.
    direct = _predict_with_prophet(FakeModel, history, HORIZON)
    assert [row[0] for row in direct] == [row[0] for row in raw]


def test_forecast_upsert_uses_the_model_version_in_the_key():
    sql = str(UPSERT_FORECAST_SQL)
    assert "INSERT INTO forecasts (skill_id, ds, yhat, yhat_lower, yhat_upper, model_version)" in sql
    assert "ON CONFLICT (skill_id, ds, model_version)" in sql


def test_prophet_stays_lazy_and_is_listed_in_requirements():
    source = (ROOT / "analytics" / "forecast.py").read_text(encoding="utf-8")
    before_loader = source.split("def _load_prophet", 1)[0]
    assert "import prophet" not in before_loader
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("prophet>=") for line in lines)

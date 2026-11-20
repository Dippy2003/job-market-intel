"""Forecast weekly skill counts eight weeks ahead.

History for a skill runs from the first week it appears through the latest
week that has any dated job. Weeks in between with no postings are zeros:
that skill was not requested, which is real demand of zero. Weeks before the
first sighting are left blank.

Prophet (``prophet-weekly-1``) is fit when that span is at least eight weeks.
The series is already one point per week and the live corpus is only a few
weeks (about 200 jobs), so yearly, weekly, and daily seasonality stay off.
A shorter span of two to seven weeks uses the linear fallback below. A skill
whose span is a single week is skipped. If Prophet is missing or the fit
fails, the same linear fallback is used whenever two weeks exist. One short
skill never aborts the run.

Linear fallback (``linear-fallback-1``)
--------------------------------------
Ordinary least squares of ``count`` on the week index, projected onto the
next eight Mondays. The band matches Prophet's 80% interval:

* Three or more weeks: 1.2816 residual standard errors (n - 2 degrees of
  freedom), and at least 5% of the largest observed count.
* Two weeks: there are no residual degrees of freedom, so the band is 20%
  of the larger of ``|yhat|`` and the largest observed count.

Counts are clipped at zero, and ``yhat_lower <= yhat <= yhat_upper``.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text

from analytics.trends import TrendPoint, week_start

log = logging.getLogger(__name__)

HORIZON = 8
MIN_PROPHET_WEEKS = 8
MIN_FALLBACK_WEEKS = 2
PROPHET_MODEL = "prophet-weekly-1"
LINEAR_MODEL = "linear-fallback-1"
# About an 80% two-sided normal interval, the same width Prophet is given.
INTERVAL_Z = Decimal("1.2815515655446004")
PEAK_FLOOR = Decimal("0.05")
TWO_POINT_BAND = Decimal("0.20")
FOUR = Decimal("0.0001")

History = list[tuple[date, float]]
RawForecast = list[tuple[date, float | Decimal, float | Decimal, float | Decimal]]
ProphetFit = Callable[[History, int], RawForecast | None]

SELECT_FORECASTS_SQL = text("SELECT skill_id, ds, model_version FROM forecasts")

SELECT_FUTURE_FORECASTS_SQL = text("""
SELECT skill_id, ds, model_version
FROM forecasts
WHERE ds > :origin
""")

UPSERT_FORECAST_SQL = text("""
INSERT INTO forecasts (skill_id, ds, yhat, yhat_lower, yhat_upper, model_version)
VALUES (:skill_id, :ds, :yhat, :yhat_lower, :yhat_upper, :model_version)
ON CONFLICT (skill_id, ds, model_version) DO UPDATE
SET yhat = EXCLUDED.yhat,
    yhat_lower = EXCLUDED.yhat_lower,
    yhat_upper = EXCLUDED.yhat_upper
""")

DELETE_FORECAST_SQL = text("""
DELETE FROM forecasts
WHERE skill_id = :skill_id AND ds = :ds AND model_version = :model_version
""")


@dataclass(frozen=True)
class ForecastPoint:
    """One future week for one skill and one model version."""

    skill_id: int
    ds: date
    yhat: Decimal
    yhat_lower: Decimal
    yhat_upper: Decimal
    model_version: str


@dataclass(frozen=True)
class ForecastBuild:
    """Forecast rows and how many skills took each path."""

    points: list[ForecastPoint]
    prophet: int
    fallback: int
    skipped: int


def series_by_skill(points: Sequence[TrendPoint], origin: date) -> dict[int, History]:
    """Weekly counts from each skill's first week through ``origin``, with gaps as zero."""
    observed: dict[int, dict[date, int]] = {}
    for point in points:
        start = week_start(point.period_start)
        if start > origin:
            continue
        observed.setdefault(point.skill_id, {})[start] = point.count
    series: dict[int, History] = {}
    for skill_id, counts in observed.items():
        day = min(counts)
        history: History = []
        while day <= origin:
            history.append((day, float(counts.get(day, 0))))
            day += timedelta(days=7)
        if history:
            series[skill_id] = history
    return series


def _decimal_value(value: float | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("forecast value is not finite")
    return Decimal(str(number))


def make_forecast_point(
    skill_id: int,
    ds: date,
    yhat: float | Decimal,
    lower: float | Decimal,
    upper: float | Decimal,
    model_version: str,
) -> ForecastPoint:
    """Clip a count forecast at zero and keep the interval ordered after rounding."""
    mid = _decimal_value(yhat)
    lo = _decimal_value(lower)
    hi = _decimal_value(upper)
    if mid < 0:
        mid = Decimal(0)
    if lo < 0:
        lo = Decimal(0)
    if hi < 0:
        hi = Decimal(0)
    if lo > mid:
        lo = mid
    if hi < mid:
        hi = mid
    mid_q = mid.quantize(FOUR, rounding=ROUND_HALF_UP)
    lo_q = lo.quantize(FOUR, rounding=ROUND_HALF_UP)
    hi_q = hi.quantize(FOUR, rounding=ROUND_HALF_UP)
    if lo_q > mid_q:
        lo_q = mid_q
    if hi_q < mid_q:
        hi_q = mid_q
    return ForecastPoint(
        skill_id=skill_id,
        ds=ds,
        yhat=mid_q,
        yhat_lower=lo_q,
        yhat_upper=hi_q,
        model_version=model_version,
    )


def linear_forecast(history: History, horizon: int) -> RawForecast:
    """Project ``history`` with the documented least-squares fallback."""
    if len(history) < MIN_FALLBACK_WEEKS:
        raise ValueError("linear fallback needs at least 2 weeks")
    if horizon < 1:
        raise ValueError("horizon must be a positive integer")
    xs = [Decimal(index) for index in range(len(history))]
    ys = [Decimal(str(value)) for _day, value in history]
    n = Decimal(len(history))
    x_mean = sum(xs, Decimal(0)) / n
    y_mean = sum(ys, Decimal(0)) / n
    var_x = sum((x - x_mean) ** 2 for x in xs)
    if var_x == 0:
        slope = Decimal(0)
    else:
        slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)) / var_x
    intercept = y_mean - slope * x_mean
    peak = max([abs(y) for y in ys] + [Decimal(1)])
    base_band: Decimal | None
    if len(history) > 2:
        fitted = [intercept + slope * x for x in xs]
        sse = sum((y - hat) ** 2 for y, hat in zip(ys, fitted, strict=True))
        sigma = (sse / (n - 2)).sqrt()
        base_band = max(INTERVAL_Z * sigma, PEAK_FLOOR * peak)
    else:
        base_band = None
    last = history[-1][0]
    points: RawForecast = []
    last_index = Decimal(len(history) - 1)
    for step in range(1, horizon + 1):
        raw = intercept + slope * (last_index + step)
        if base_band is None:
            band = TWO_POINT_BAND * max(abs(raw), peak)
        else:
            band = base_band
        lower = raw - band
        upper = raw + band
        points.append((last + timedelta(days=7 * step), raw, lower, upper))
    return points


def _load_prophet():
    """Import Prophet when a fit is actually requested.

    Interactive plots are unused here. Prophet logs an error when plotly is
    absent, so that logger is quieted before the import.
    """
    logging.getLogger("prophet.plot").setLevel(logging.CRITICAL)
    logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
    from prophet import Prophet

    return Prophet


def _coerce_prophet_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return value.date()


def _predict_with_prophet(prophet_cls, history: History, horizon: int) -> RawForecast:
    import pandas as pd

    frame = pd.DataFrame(
        {
            "ds": [datetime(day.year, day.month, day.day) for day, _value in history],
            "y": [float(value) for _day, value in history],
        }
    )
    model = prophet_cls(
        growth="linear",
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=0.8,
        uncertainty_samples=200,
        n_changepoints=min(8, max(len(history) - 2, 0)),
    )
    model.fit(frame)
    future = model.make_future_dataframe(periods=horizon, freq="W-MON", include_history=False)
    predicted = model.predict(future)
    last = history[-1][0]
    found: RawForecast = []
    for row in predicted.itertuples(index=False):
        ds = week_start(_coerce_prophet_date(row.ds))
        if ds <= last:
            continue
        yhat = float(row.yhat)
        lower = float(getattr(row, "yhat_lower", yhat))
        upper = float(getattr(row, "yhat_upper", yhat))
        found.append((ds, yhat, lower, upper))
    deduped: RawForecast = []
    seen: set[date] = set()
    for ds, yhat, lower, upper in sorted(found, key=lambda item: item[0]):
        if ds in seen:
            continue
        seen.add(ds)
        deduped.append((ds, yhat, lower, upper))
        if len(deduped) == horizon:
            break
    if not deduped:
        raise ValueError("Prophet returned no future weeks")
    return deduped


def fit_prophet(history: History, horizon: int) -> RawForecast | None:
    """Fit Prophet. ``None`` means it is missing or the fit failed, so the caller falls back."""
    try:
        prophet_cls = _load_prophet()
    except ImportError:
        log.warning("prophet is not installed; using the linear fallback")
        return None
    try:
        logging.getLogger("prophet").setLevel(logging.WARNING)
        logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
        return _predict_with_prophet(prophet_cls, history, horizon)
    except Exception:
        log.warning("Prophet fit failed for %s weeks; using the linear fallback", len(history), exc_info=True)
        return None


def build_forecasts(
    points: Sequence[TrendPoint],
    origin: date | None,
    *,
    horizon: int = HORIZON,
    min_prophet_weeks: int = MIN_PROPHET_WEEKS,
    fit: ProphetFit | None = None,
) -> ForecastBuild:
    """Forecast every skill that has at least two weeks. Short skills are skipped."""
    if horizon < 1:
        raise ValueError("horizon must be a positive integer")
    if min_prophet_weeks < MIN_FALLBACK_WEEKS:
        raise ValueError("min_prophet_weeks must be at least 2")
    if fit is None:
        fit = fit_prophet
    if origin is None:
        return ForecastBuild(points=[], prophet=0, fallback=0, skipped=0)
    series = series_by_skill(points, origin)
    made: list[ForecastPoint] = []
    prophet = 0
    fallback = 0
    skipped = 0
    for skill_id in sorted(series):
        history = series[skill_id]
        if len(history) < MIN_FALLBACK_WEEKS:
            skipped += 1
            log.debug("Skipping skill %s: %s week of history", skill_id, len(history))
            continue
        raw: RawForecast | None = None
        version = LINEAR_MODEL
        if len(history) >= min_prophet_weeks:
            try:
                raw = fit(history, horizon)
            except Exception:
                log.warning(
                    "Prophet fit raised for skill %s; using the linear fallback",
                    skill_id,
                    exc_info=True,
                )
                raw = None
            if raw:
                version = PROPHET_MODEL
                prophet += 1
            else:
                raw = linear_forecast(history, horizon)
                fallback += 1
        else:
            raw = linear_forecast(history, horizon)
            fallback += 1
        for ds, yhat, lower, upper in raw:
            made.append(make_forecast_point(skill_id, week_start(ds), yhat, lower, upper, version))
    made.sort(key=lambda point: (point.skill_id, point.ds))
    log.info(
        "Forecasts: %s prophet, %s linear fallback, %s skipped",
        prophet,
        fallback,
        skipped,
    )
    return ForecastBuild(points=made, prophet=prophet, fallback=fallback, skipped=skipped)


def _coerce_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def sync_forecasts(conn, points: Sequence[ForecastPoint], *, origin: date | None) -> int:
    """Upsert future weeks and drop future rows this run did not produce. Returns deletions.

    Rows on or before ``origin`` are previous forecasts and are left in place.
    With no dated jobs, every forecast row is cleared so the table matches the empty corpus.
    """
    if origin is None:
        existing = conn.execute(SELECT_FORECASTS_SQL).all()
    else:
        existing = conn.execute(SELECT_FUTURE_FORECASTS_SQL, {"origin": origin}).all()
    keep = {(point.skill_id, point.ds, point.model_version) for point in points}
    removed = 0
    for row in existing:
        key = (int(row.skill_id), _coerce_date(row.ds), str(row.model_version))
        if key in keep:
            continue
        conn.execute(
            DELETE_FORECAST_SQL,
            {"skill_id": key[0], "ds": key[1], "model_version": key[2]},
        )
        removed += 1
    for point in points:
        conn.execute(
            UPSERT_FORECAST_SQL,
            {
                "skill_id": point.skill_id,
                "ds": point.ds,
                "yhat": point.yhat,
                "yhat_lower": point.yhat_lower,
                "yhat_upper": point.yhat_upper,
                "model_version": point.model_version,
            },
        )
    log.info("Forecast rows: %s upserted, %s future rows removed", len(points), removed)
    return removed

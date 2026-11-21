"""Streamlit view of the read-only job market API.

Run from the project root:

    streamlit run dashboard/app.py
"""
from __future__ import annotations

import inspect
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from api_client import (
    API_UNREACHABLE,
    APIClientError,
    api_base_url,
    get_forecasts,
    get_health,
    get_jobs,
    get_roles,
    get_trends,
)

PAGE_SIZE = 50
DEFAULT_WEEKS = 12
DEFAULT_TOP_SKILLS = 8
PREFERRED_MODEL = "prophet-weekly-1"
# Streamlit 1.4x renamed use_container_width to width="stretch" and warns on the old name.
_TABLE_WIDTH: dict[str, Any] = (
    {"width": "stretch"}
    if "width" in inspect.signature(st.dataframe).parameters
    else {"use_container_width": True}
)

st.set_page_config(page_title="Job Market Intelligence", layout="wide")


@st.cache_data(ttl=600)
def load_health() -> dict[str, Any]:
    return get_health()


@st.cache_data(ttl=600)
def load_jobs(source: str, keyword: str, skill: str, limit: int, offset: int) -> dict[str, Any]:
    return get_jobs(source=source or None, q=keyword or None, skill=skill or None, limit=limit, offset=offset)


@st.cache_data(ttl=600)
def load_skill_names() -> tuple[str, ...]:
    """Skill names, longest weekly history first, so the chart opens on a real line."""
    body = get_trends()
    ranked: list[tuple[int, str]] = []
    for item in body.get("items") or []:
        skill = item.get("skill")
        if not skill:
            continue
        ranked.append((len(item.get("points") or []), str(skill)))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return tuple(dict.fromkeys(name for _count, name in ranked))


@st.cache_data(ttl=600)
def load_trends(skill: str, weeks: int) -> dict[str, Any]:
    return get_trends(skill=skill or None, weeks=weeks)


@st.cache_data(ttl=600)
def load_forecasts() -> dict[str, Any]:
    return get_forecasts()


@st.cache_data(ttl=600)
def load_roles() -> dict[str, Any]:
    return get_roles()


def _load(func: Any, *args: Any) -> tuple[Any, APIClientError | None]:
    try:
        return func(*args), None
    except APIClientError as exc:
        return None, exc


def _unreachable() -> None:
    st.error(
        f"{API_UNREACHABLE}. Start the API in another terminal with "
        "uvicorn api.main:app, then refresh this page."
    )


def _jobs_frame(items: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for job in items:
        skills = job.get("skills") or []
        if not isinstance(skills, list):
            skills = []
        rows.append(
            {
                "Title": job.get("title"),
                "Company": job.get("company"),
                "Location": job.get("location"),
                "Source": job.get("source"),
                "Posted": job.get("posted_date"),
                "Skills": ", ".join(str(name) for name in skills),
                "URL": job.get("url"),
            }
        )
    return pd.DataFrame(rows)


def _one_model(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One forecast row per week. Prophet wins when two models share a date."""
    chosen: dict[str, dict[str, Any]] = {}
    for point in points:
        week = str(point.get("ds") or "")
        if not week:
            continue
        current = chosen.get(week)
        if current is None:
            chosen[week] = point
            continue
        if point.get("model_version") == PREFERRED_MODEL and current.get("model_version") != PREFERRED_MODEL:
            chosen[week] = point
    return [chosen[week] for week in sorted(chosen)]


def _ranked_forecasts(
    items: list[dict[str, Any]], top_n: int
) -> list[tuple[float, dict[str, Any], list[dict[str, Any]]]]:
    ranked: list[tuple[float, dict[str, Any], list[dict[str, Any]]]] = []
    for item in items:
        points = _one_model(list(item.get("points") or []))
        if not points:
            continue
        latest = float(points[-1]["yhat"])
        ranked.append((latest, item, points))
    ranked.sort(key=lambda row: (-row[0], str(row[1].get("skill") or "")))
    return ranked[:top_n]


def _forecast_chart(items: list[dict[str, Any]], top_n: int) -> pd.DataFrame:
    by_week: dict[str, dict[str, float]] = {}
    columns: list[str] = []
    for _latest, item, points in _ranked_forecasts(items, top_n):
        skill = str(item.get("skill") or "")
        columns.append(skill)
        for point in points:
            by_week.setdefault(str(point["ds"]), {})[skill] = float(point["yhat"])
    frame = pd.DataFrame.from_dict(by_week, orient="index")
    if frame.empty:
        return frame
    frame = frame.reindex(columns=columns)
    frame.index = pd.to_datetime(frame.index)
    return frame.sort_index()


def _forecast_table(items: list[dict[str, Any]], top_n: int) -> pd.DataFrame:
    rows = []
    for latest, item, points in _ranked_forecasts(items, top_n):
        last = points[-1]
        rows.append(
            {
                "Skill": item.get("skill"),
                "Category": item.get("category"),
                "Latest week": last.get("ds"),
                "Forecast": latest,
                "Lower": float(last["yhat_lower"]),
                "Upper": float(last["yhat_upper"]),
                "Model": last.get("model_version"),
            }
        )
    return pd.DataFrame(rows)


def _render_jobs() -> None:
    source_col, keyword_col, skill_col = st.columns(3)
    with source_col:
        source = st.selectbox("Source", ("All", "itpro", "topjobs"))
    with keyword_col:
        keyword = st.text_input("Keyword", placeholder="Title, company, location, or description")
    with skill_col:
        skill = st.text_input(
            "Skill",
            placeholder="Exact name, for example Python",
            help="Exact skill name, case-insensitive. Java matches only Java.",
        )
    page = int(st.number_input("Page", min_value=1, step=1, value=1))
    offset = (page - 1) * PAGE_SIZE
    body, error = _load(
        load_jobs,
        "" if source == "All" else source,
        keyword.strip(),
        skill.strip(),
        PAGE_SIZE,
        offset,
    )
    if error is not None or body is None:
        _unreachable()
        return
    items = body.get("items") or []
    total = int(body.get("total") or 0)
    if total == 0:
        st.info("No jobs match these filters.")
        return
    if not items:
        st.info("This page is past the last matching job.")
        return
    st.caption(f"Showing {offset + 1}-{offset + len(items)} of {total}.")
    st.dataframe(
        _jobs_frame(items),
        column_config={"URL": st.column_config.LinkColumn("URL")},
        hide_index=True,
        **_TABLE_WIDTH,
    )


def _render_trends() -> None:
    names, error = _load(load_skill_names)
    if error is not None or names is None:
        _unreachable()
        return
    if not names:
        st.info("No skill trends yet. Run python -m pipeline.compute_trends.")
        return
    skill_col, weeks_col = st.columns((2, 1))
    with skill_col:
        skill = st.selectbox("Skill", names)
    with weeks_col:
        weeks = int(st.slider("Weeks", min_value=1, max_value=52, value=DEFAULT_WEEKS))
    body, error = _load(load_trends, skill, weeks)
    if error is not None or body is None:
        _unreachable()
        return
    series = next((item for item in body.get("items") or [] if item.get("skill") == skill), None)
    points = [] if series is None else list(series.get("points") or [])
    if series is None or not points:
        st.info("No trend points for this skill in the selected window.")
        return
    frame = pd.DataFrame(points)
    frame["period_start"] = pd.to_datetime(frame["period_start"])
    frame["count"] = pd.to_numeric(frame["count"])
    frame["share"] = pd.to_numeric(frame["share"])
    category = series.get("category")
    st.subheader(skill if not category else f"{skill} ({category})")
    st.caption("Jobs that mention this skill each week.")
    st.altair_chart(_trend_chart(frame, "count", "Jobs"), width="stretch")
    st.caption("Share of that week's jobs.")
    st.altair_chart(_trend_chart(frame, "share", "Share"), width="stretch")
    table = frame.rename(columns={"period_start": "Week", "count": "Jobs", "share": "Share"})
    st.dataframe(table[["Week", "Jobs", "Share"]], hide_index=True, **_TABLE_WIDTH)


def _trend_chart(frame: pd.DataFrame, y: str, title: str) -> alt.Chart:
    """Line plus point, so a skill with one stored week is still visible."""
    return (
        alt.Chart(frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("period_start:T", title="Week"),
            y=alt.Y(f"{y}:Q", title=title, scale=alt.Scale(zero=True, nice=True)),
            tooltip=["period_start:T", alt.Tooltip(f"{y}:Q", title=title)],
        )
        .properties(height=280)
    )


def _render_forecasts() -> None:
    top_n = int(st.slider("Top skills", min_value=1, max_value=20, value=DEFAULT_TOP_SKILLS))
    body, error = _load(load_forecasts)
    if error is not None or body is None:
        _unreachable()
        return
    items = list(body.get("items") or [])
    chart = _forecast_chart(items, top_n)
    if chart.empty:
        st.info("No forecasts yet. Run python -m pipeline.compute_trends.")
        return
    horizon = body.get("horizon_weeks", 8)
    st.caption(f"{horizon}-week forecast stored by the pipeline. Prophet is preferred when two models exist.")
    st.line_chart(chart)
    st.dataframe(_forecast_table(items, top_n), hide_index=True, **_TABLE_WIDTH)


def _render_roles() -> None:
    body, error = _load(load_roles)
    if error is not None or body is None:
        _unreachable()
        return
    items = list(body.get("items") or [])
    if not items:
        st.info("No role clusters yet. Run python -m pipeline.cluster_roles.")
        return
    frame = pd.DataFrame(
        {
            "Role": [item.get("label") for item in items],
            "Jobs": [int(item.get("job_count") or 0) for item in items],
            "Top skills": [", ".join(item.get("top_skills") or []) for item in items],
        }
    )
    st.bar_chart(frame.set_index("Role")[["Jobs"]])
    st.dataframe(frame, hide_index=True, **_TABLE_WIDTH)


st.title("Job Market Intelligence")
st.caption("Sri Lankan tech job ads, weekly skill demand, 8-week forecasts, and role clusters.")

health, health_error = _load(load_health)
if health_error is not None or health is None:
    _unreachable()
    st.stop()

st.caption(f"API {health.get('status', 'ok')} at {api_base_url()}. Results are cached for 10 minutes.")

jobs_tab, trends_tab, forecasts_tab, roles_tab = st.tabs(
    ["Jobs", "Skill trends", "Forecasts", "Roles"]
)
with jobs_tab:
    _render_jobs()
with trends_tab:
    _render_trends()
with forecasts_tab:
    _render_forecasts()
with roles_tab:
    _render_roles()

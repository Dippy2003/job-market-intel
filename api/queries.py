"""Read queries for the API.

Trends and forecasts are read from the tables the pipeline already filled.
They are not recomputed here. ``text[]`` columns are cast to text so PostgreSQL
and the SQLite tests see the same array literal.
"""
from __future__ import annotations

from sqlalchemy import Text, cast, exists, func, select
from sqlalchemy.orm import Session

from analytics.forecast import HORIZON
from api.schemas import (
    ForecastPointOut,
    JobListResponse,
    JobOut,
    RoleDetail,
    RoleJobOut,
    RoleListResponse,
    RoleOut,
    SkillForecastOut,
    SkillForecastsResponse,
    SkillTrendSeries,
    SkillTrendsResponse,
    TrendPointOut,
)
from db.models import Forecast, Job, JobRoleCluster, JobSkill, RoleCluster, Skill, SkillTrend


def as_text_list(value: object) -> list[str]:
    """Normalize a PostgreSQL ``text[]`` value or the text form of one."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return ["" if item is None else str(item) for item in value]
    if isinstance(value, str):
        return _parse_pg_text_array(value)
    raise TypeError(f"expected a text array, got {type(value).__name__}")


def _parse_pg_text_array(value: str) -> list[str]:
    """Parse ``{a,"b c"}`` the way PostgreSQL prints a text array."""
    text = value.strip()
    if text == "":
        return []
    if len(text) < 2 or text[0] != "{" or text[-1] != "}":
        raise ValueError("expected a PostgreSQL text array")
    if text == "{}":
        return []
    items: list[str] = []
    token: list[str] = []
    quoted = False
    index = 1
    last = len(text) - 1
    while index < last:
        char = text[index]
        if char == "\\" and index + 1 < last:
            token.append(text[index + 1])
            index += 2
            continue
        if char == '"':
            quoted = not quoted
            index += 1
            continue
        if char == "," and not quoted:
            items.append("".join(token))
            token = []
            index += 1
            continue
        token.append(char)
        index += 1
    items.append("".join(token))
    return items


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _like_pattern(term: str) -> str:
    """Case-insensitive contains match. ``%`` and ``_`` in the term stay literal."""
    escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _skill_names(session: Session, job_ids: list[int]) -> dict[int, list[str]]:
    if not job_ids:
        return {}
    rows = session.execute(
        select(JobSkill.job_id, Skill.name)
        .join(Skill, Skill.id == JobSkill.skill_id)
        .where(JobSkill.job_id.in_(job_ids))
        .order_by(JobSkill.job_id.asc(), Skill.name.asc())
    ).all()
    names: dict[int, list[str]] = {}
    for job_id, name in rows:
        names.setdefault(int(job_id), []).append(str(name))
    return names


def fetch_jobs(
    session: Session,
    *,
    source: str | None,
    q: str | None,
    skill: str | None,
    limit: int,
    offset: int,
) -> JobListResponse:
    """Jobs newest-first. ``skill`` is an exact name, so Java does not match JavaScript."""
    filters = []
    source_name = _clean(source)
    query = _clean(q)
    skill_name = _clean(skill)
    if source_name is not None:
        filters.append(func.lower(Job.source) == source_name.lower())
    if query is not None:
        pattern = _like_pattern(query)
        searchable = (
            Job.title,
            func.coalesce(Job.company, ""),
            func.coalesce(Job.location, ""),
            func.coalesce(Job.description, ""),
        )
        filters.append(
            func.lower(searchable[0]).like(pattern, escape="\\")
            | func.lower(searchable[1]).like(pattern, escape="\\")
            | func.lower(searchable[2]).like(pattern, escape="\\")
            | func.lower(searchable[3]).like(pattern, escape="\\")
        )
    if skill_name is not None:
        filters.append(
            exists(
                select(JobSkill.job_id)
                .join(Skill, Skill.id == JobSkill.skill_id)
                .where(
                    JobSkill.job_id == Job.id,
                    func.lower(Skill.name) == skill_name.lower(),
                )
            )
        )
    count_stmt = select(func.count()).select_from(Job)
    list_stmt = select(Job)
    if filters:
        count_stmt = count_stmt.where(*filters)
        list_stmt = list_stmt.where(*filters)
    total = int(session.scalar(count_stmt) or 0)
    rows = session.scalars(
        list_stmt.order_by(Job.scraped_at.desc(), Job.id.desc()).limit(limit).offset(offset)
    ).all()
    skills = _skill_names(session, [int(row.id) for row in rows])
    items = [
        JobOut(
            id=int(row.id),
            source=row.source,
            url=row.url,
            title=row.title,
            company=row.company,
            location=row.location,
            salary_min=row.salary_min,
            salary_max=row.salary_max,
            description=row.description,
            posted_date=row.posted_date,
            closing_date=row.closing_date,
            scraped_at=row.scraped_at,
            duplicate_of=None if row.duplicate_of is None else int(row.duplicate_of),
            skills=skills.get(int(row.id), []),
        )
        for row in rows
    ]
    return JobListResponse(items=items, total=total, limit=limit, offset=offset)


def _recent_periods(session: Session, *, skill: str | None, weeks: int | None) -> list[object] | None:
    """The newest ``weeks`` Mondays. ``None`` means the caller wants every week."""
    if weeks is None:
        return None
    stmt = select(SkillTrend.period_start)
    if skill is not None:
        stmt = stmt.join(Skill, Skill.id == SkillTrend.skill_id).where(
            func.lower(Skill.name) == skill.lower()
        )
    stmt = stmt.distinct().order_by(SkillTrend.period_start.desc()).limit(weeks)
    return list(session.scalars(stmt).all())


def fetch_trends(session: Session, *, skill: str | None, weeks: int | None) -> SkillTrendsResponse:
    """Weekly demand from ``skill_trends``, optionally one skill and the newest N weeks."""
    skill_name = _clean(skill)
    periods = _recent_periods(session, skill=skill_name, weeks=weeks)
    if periods is not None and not periods:
        return SkillTrendsResponse(items=[])
    stmt = (
        select(
            Skill.id.label("skill_id"),
            Skill.name.label("skill"),
            Skill.category,
            SkillTrend.period_start,
            SkillTrend.count,
            SkillTrend.share,
        )
        .join(SkillTrend, SkillTrend.skill_id == Skill.id)
        .order_by(Skill.name.asc(), SkillTrend.period_start.asc())
    )
    if skill_name is not None:
        stmt = stmt.where(func.lower(Skill.name) == skill_name.lower())
    if periods is not None:
        stmt = stmt.where(SkillTrend.period_start.in_(periods))
    grouped: dict[int, SkillTrendSeries] = {}
    for row in session.execute(stmt).all():
        series = grouped.get(int(row.skill_id))
        if series is None:
            series = SkillTrendSeries(
                skill_id=int(row.skill_id),
                skill=str(row.skill),
                category=row.category,
                points=[],
            )
            grouped[int(row.skill_id)] = series
        series.points.append(
            TrendPointOut(period_start=row.period_start, count=int(row.count), share=row.share)
        )
    return SkillTrendsResponse(items=list(grouped.values()))


def fetch_forecasts(session: Session, *, skill: str | None) -> SkillForecastsResponse:
    """The newest ``HORIZON`` forecast weeks stored for each skill."""
    skill_name = _clean(skill)
    stmt = (
        select(
            Skill.id.label("skill_id"),
            Skill.name.label("skill"),
            Skill.category,
            Forecast.ds,
            Forecast.yhat,
            Forecast.yhat_lower,
            Forecast.yhat_upper,
            Forecast.model_version,
        )
        .join(Forecast, Forecast.skill_id == Skill.id)
        .order_by(Skill.name.asc(), Forecast.ds.asc(), Forecast.model_version.asc())
    )
    if skill_name is not None:
        stmt = stmt.where(func.lower(Skill.name) == skill_name.lower())
    pending: dict[int, tuple[str, str | None, list[ForecastPointOut]]] = {}
    for row in session.execute(stmt).all():
        skill_id = int(row.skill_id)
        name, category, points = pending.get(skill_id, (str(row.skill), row.category, []))
        points.append(
            ForecastPointOut(
                ds=row.ds,
                yhat=row.yhat,
                yhat_lower=row.yhat_lower,
                yhat_upper=row.yhat_upper,
                model_version=str(row.model_version),
            )
        )
        pending[skill_id] = (name, category, points)
    items: list[SkillForecastOut] = []
    for skill_id, (name, category, points) in pending.items():
        dates = sorted({point.ds for point in points})
        keep = set(dates[-HORIZON:])
        items.append(
            SkillForecastOut(
                skill_id=skill_id,
                skill=name,
                category=category,
                points=[point for point in points if point.ds in keep],
            )
        )
    return SkillForecastsResponse(horizon_weeks=HORIZON, items=items)


def _role_from_row(row) -> RoleOut:
    return RoleOut(
        id=int(row.id),
        label=str(row.label),
        top_skills=as_text_list(row.top_skills),
        job_count=int(row.size),
        run_at=row.run_at,
    )


def _role_rows(session: Session, role_id: int | None = None):
    stmt = select(
        RoleCluster.id,
        RoleCluster.label,
        cast(RoleCluster.top_skills, Text).label("top_skills"),
        RoleCluster.size,
        RoleCluster.run_at,
    ).order_by(RoleCluster.size.desc(), RoleCluster.label.asc(), RoleCluster.id.asc())
    if role_id is not None:
        stmt = stmt.where(RoleCluster.id == role_id)
    return session.execute(stmt).all()


def fetch_roles(session: Session) -> RoleListResponse:
    """Clusters from ``role_clusters``. ``job_count`` is the stored cluster size."""
    return RoleListResponse(items=[_role_from_row(row) for row in _role_rows(session)])


def fetch_role(session: Session, role_id: int) -> RoleDetail | None:
    """One cluster and the jobs linked in ``job_role_clusters``. Missing ids return None."""
    rows = _role_rows(session, role_id)
    if not rows:
        return None
    role = _role_from_row(rows[0])
    job_rows = session.execute(
        select(Job.id, Job.source, Job.url, Job.title, Job.company, Job.location)
        .join(JobRoleCluster, JobRoleCluster.job_id == Job.id)
        .where(JobRoleCluster.cluster_id == role_id)
        .order_by(Job.title.asc(), Job.id.asc())
    ).all()
    jobs = [
        RoleJobOut(
            id=int(row.id),
            source=row.source,
            url=row.url,
            title=row.title,
            company=row.company,
            location=row.location,
        )
        for row in job_rows
    ]
    return RoleDetail(
        id=role.id,
        label=role.label,
        top_skills=role.top_skills,
        job_count=role.job_count,
        run_at=role.run_at,
        jobs=jobs,
    )

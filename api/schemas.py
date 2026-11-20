"""Response models for the read-only API."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Process is up. This check does not open the database."""

    status: str = "ok"


class JobOut(BaseModel):
    """One scraped posting, with the skill names extracted from it."""

    id: int
    source: str
    url: str
    title: str
    company: str | None = None
    location: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    description: str | None = None
    posted_date: date | None = None
    closing_date: date | None = None
    scraped_at: datetime
    duplicate_of: int | None = None
    skills: list[str] = Field(default_factory=list)


class JobListResponse(BaseModel):
    """One page of jobs. ``total`` counts every row that matches the filters."""

    items: list[JobOut]
    total: int
    limit: int
    offset: int


class TrendPointOut(BaseModel):
    """Demand for one skill in the week that starts on ``period_start`` (a Monday)."""

    period_start: date
    count: int
    share: Decimal


class SkillTrendSeries(BaseModel):
    """Weekly demand for one skill, oldest week first."""

    skill_id: int
    skill: str
    category: str | None = None
    points: list[TrendPointOut]


class SkillTrendsResponse(BaseModel):
    """Rows from ``skill_trends``. The API does not recompute them."""

    items: list[SkillTrendSeries]


class ForecastPointOut(BaseModel):
    """One forecast week for one model version."""

    ds: date
    yhat: Decimal
    yhat_lower: Decimal
    yhat_upper: Decimal
    model_version: str


class SkillForecastOut(BaseModel):
    """The latest forecast weeks stored for one skill."""

    skill_id: int
    skill: str
    category: str | None = None
    points: list[ForecastPointOut]


class SkillForecastsResponse(BaseModel):
    """Eight-week forecasts already stored in ``forecasts``."""

    horizon_weeks: int
    items: list[SkillForecastOut]


class RoleOut(BaseModel):
    """One role cluster from the latest clustering run."""

    id: int
    label: str
    top_skills: list[str]
    job_count: int
    run_at: datetime


class RoleListResponse(BaseModel):
    """Role clusters, largest first."""

    items: list[RoleOut]


class RoleJobOut(BaseModel):
    """A job assigned to a role cluster."""

    id: int
    source: str
    url: str
    title: str
    company: str | None = None
    location: str | None = None


class RoleDetail(RoleOut):
    """A role cluster plus the jobs currently assigned to it."""

    jobs: list[RoleJobOut]

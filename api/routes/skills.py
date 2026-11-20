"""Skill demand and forecast routes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_db
from api.queries import fetch_forecasts, fetch_trends
from api.schemas import SkillForecastsResponse, SkillTrendsResponse

router = APIRouter(tags=["skills"])


@router.get("/skills/trends", response_model=SkillTrendsResponse, summary="Weekly skill demand")
def list_trends(
    session: Annotated[Session, Depends(get_db)],
    skill: Annotated[
        str | None,
        Query(description="Exact skill name, case-insensitive."),
    ] = None,
    weeks: Annotated[
        int | None,
        Query(ge=1, le=520, description="Newest N weeks. Omit it to return every stored week."),
    ] = None,
) -> SkillTrendsResponse:
    """Read ``skill_trends``. Weeks are not recomputed on request."""
    return fetch_trends(session, skill=skill, weeks=weeks)


@router.get(
    "/skills/forecasts",
    response_model=SkillForecastsResponse,
    summary="Eight-week skill forecasts",
)
def list_forecasts(
    session: Annotated[Session, Depends(get_db)],
    skill: Annotated[
        str | None,
        Query(description="Exact skill name, case-insensitive. Omit it to return every skill."),
    ] = None,
) -> SkillForecastsResponse:
    """The newest eight forecast weeks stored for each skill."""
    return fetch_forecasts(session, skill=skill)

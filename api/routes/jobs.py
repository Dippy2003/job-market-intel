"""Job listing route."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_db
from api.queries import fetch_jobs
from api.schemas import JobListResponse

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=JobListResponse, summary="List job postings")
def list_jobs(
    session: Annotated[Session, Depends(get_db)],
    source: Annotated[
        str | None,
        Query(description="Scraper name, for example itpro, topjobs, xpressjobs, or ikman."),
    ] = None,
    q: Annotated[
        str | None,
        Query(description="Case-insensitive match on title, company, location, or description."),
    ] = None,
    skill: Annotated[
        str | None,
        Query(description="Exact skill name, case-insensitive. Java does not match JavaScript."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size.")] = 50,
    offset: Annotated[int, Query(ge=0, description="Rows to skip.")] = 0,
) -> JobListResponse:
    """Newest posts first. Duplicates stay in the list and set ``duplicate_of``."""
    return fetch_jobs(session, source=source, q=q, skill=skill, limit=limit, offset=offset)

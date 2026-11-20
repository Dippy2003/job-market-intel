"""Role cluster routes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_db
from api.queries import fetch_role, fetch_roles
from api.schemas import RoleDetail, RoleListResponse

router = APIRouter(tags=["roles"])


@router.get("/roles", response_model=RoleListResponse, summary="List role clusters")
def list_roles(session: Annotated[Session, Depends(get_db)]) -> RoleListResponse:
    """Each cluster includes its top skills and how many jobs it holds."""
    return fetch_roles(session)


@router.get("/roles/{id}", response_model=RoleDetail, summary="Get one role cluster")
def get_role(id: int, session: Annotated[Session, Depends(get_db)]) -> RoleDetail:
    """The cluster and the jobs assigned to it."""
    role = fetch_role(session, id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return role

"""Liveness route."""
from __future__ import annotations

from fastapi import APIRouter

from api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health() -> HealthResponse:
    """The process is serving requests. This does not open the database."""
    return HealthResponse(status="ok")

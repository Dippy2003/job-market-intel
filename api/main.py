"""Read-only HTTP API for jobs, skill demand, forecasts, and role clusters.

Run it with ``uvicorn api.main:app``. ``DATABASE_URL`` is read by ``config.py``
from the environment or a local ``.env`` file. Interactive docs are at ``/docs``.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health, jobs, roles, skills
from config import get_settings, setup_logging


def cors_origin_list(value: str) -> list[str]:
    """Split ``CORS_ORIGINS``. Blank pieces are dropped."""
    return [part.strip() for part in value.split(",") if part.strip()]


def create_app() -> FastAPI:
    """Build the app. The database is opened per request, not at import."""
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="Job Market Intelligence API",
        summary="Read-only access to Sri Lankan tech job ads, skill demand, forecasts, and role clusters.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origin_list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(skills.router)
    app.include_router(roles.router)
    return app


app = create_app()

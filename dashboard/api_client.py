"""HTTP helpers for the read-only Job Market Intelligence API.

``API_BASE_URL`` sets the origin (default ``http://127.0.0.1:8000``). When that
variable is unset, a local ``.env`` is loaded. Database credentials stay in
``config.py`` and are not read here.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 10
API_UNREACHABLE = "API not reachable"


class APIClientError(Exception):
    """The API did not respond, or the body was not a JSON object."""


def api_base_url() -> str:
    """Return the API origin without a trailing slash."""
    configured = os.environ.get("API_BASE_URL", "").strip()
    if not configured:
        load_dotenv(_ENV_FILE)
        configured = os.environ.get("API_BASE_URL", "").strip()
    return (configured or DEFAULT_BASE_URL).rstrip("/")


def _query(values: dict[str, Any]) -> dict[str, Any] | None:
    """Drop empty filters. ``requests`` would otherwise send the text ``None``."""
    params: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            continue
        params[key] = value
    return params or None


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{api_base_url()}{path}",
            params=params,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as exc:
        raise APIClientError(API_UNREACHABLE) from exc
    if not isinstance(body, dict):
        raise APIClientError(API_UNREACHABLE)
    return body


def get_health() -> dict[str, Any]:
    """GET /health."""
    return _get("/health")


def get_jobs(
    source: str | None = None,
    q: str | None = None,
    skill: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """GET /jobs. ``q`` matches title, company, location, or description."""
    return _get(
        "/jobs",
        _query(
            {
                "source": source,
                "q": q,
                "skill": skill,
                "limit": limit,
                "offset": offset,
            }
        ),
    )


def get_trends(skill: str | None = None, weeks: int | None = None) -> dict[str, Any]:
    """GET /skills/trends. ``weeks`` keeps the newest N weeks."""
    return _get("/skills/trends", _query({"skill": skill, "weeks": weeks}))


def get_forecasts(skill: str | None = None) -> dict[str, Any]:
    """GET /skills/forecasts. Omit ``skill`` to return every stored forecast."""
    return _get("/skills/forecasts", _query({"skill": skill}))


def get_roles() -> dict[str, Any]:
    """GET /roles. Each cluster includes its top skills and job count."""
    return _get("/roles")

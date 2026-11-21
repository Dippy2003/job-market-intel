"""Dashboard API client. ``requests`` is mocked. No live network calls."""
from __future__ import annotations

import socket
from pathlib import Path

import pytest
import requests

from dashboard.api_client import (
    APIClientError,
    get_forecasts,
    get_health,
    get_jobs,
    get_roles,
    get_trends,
)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Fail the test if a helper opens a socket or reads a developer .env."""

    def explode(*args, **kwargs):
        raise AssertionError("live network call")

    monkeypatch.setattr(socket, "create_connection", explode)
    monkeypatch.setattr("dashboard.api_client.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("API_BASE_URL", raising=False)


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _install(monkeypatch, payload: object, status_code: int = 200) -> list[dict]:
    calls: list[dict] = []

    def fake_get(url, params=None, timeout=None, **kwargs):
        calls.append({"url": url, "params": params, "timeout": timeout, "kwargs": kwargs})
        return _Response(payload, status_code)

    monkeypatch.setattr("dashboard.api_client.requests.get", fake_get)
    return calls


def test_get_jobs_url_params_and_parsing(monkeypatch):
    payload = {
        "items": [
            {
                "id": 1,
                "source": "itpro",
                "title": "Backend Engineer",
                "skills": ["Python", "SQL"],
            }
        ],
        "total": 1,
        "limit": 10,
        "offset": 20,
    }
    calls = _install(monkeypatch, payload)
    parsed = get_jobs(source=" itpro ", q=" python ", skill="Python", limit=10, offset=20)
    assert calls[0]["url"] == "http://127.0.0.1:8000/jobs"
    assert calls[0]["params"] == {
        "source": "itpro",
        "q": "python",
        "skill": "Python",
        "limit": 10,
        "offset": 20,
    }
    assert calls[0]["timeout"] == 10
    assert calls[0]["kwargs"] == {}
    assert parsed == payload
    assert parsed["items"][0]["skills"] == ["Python", "SQL"]
    assert parsed["total"] == 1


def test_get_jobs_omits_blank_filters(monkeypatch):
    payload = {"items": [], "total": 0, "limit": 50, "offset": 0}
    calls = _install(monkeypatch, payload)
    parsed = get_jobs(source="  ", q="", skill=None)
    assert calls[0]["url"] == "http://127.0.0.1:8000/jobs"
    assert calls[0]["params"] == {"limit": 50, "offset": 0}
    assert calls[0]["timeout"] == 10
    assert parsed["items"] == []
    assert parsed["total"] == 0


def test_get_trends_url_params_and_parsing(monkeypatch):
    payload = {
        "items": [
            {
                "skill_id": 1,
                "skill": "Python",
                "category": "language",
                "points": [{"period_start": "2026-11-16", "count": 4, "share": "0.800000"}],
            }
        ]
    }
    calls = _install(monkeypatch, payload)
    parsed = get_trends(skill="Python", weeks=12)
    assert calls[0]["url"] == "http://127.0.0.1:8000/skills/trends"
    assert calls[0]["params"] == {"skill": "Python", "weeks": 12}
    assert calls[0]["timeout"] == 10
    assert parsed["items"][0]["points"][0]["count"] == 4
    assert parsed["items"][0]["points"][0]["share"] == "0.800000"

    calls.clear()
    assert get_trends() == payload
    assert calls[0]["params"] is None
    assert calls[0]["url"] == "http://127.0.0.1:8000/skills/trends"

    calls.clear()
    get_trends(weeks=4)
    assert calls[0]["params"] == {"weeks": 4}


def test_get_forecasts_url_params_and_parsing(monkeypatch):
    payload = {
        "horizon_weeks": 8,
        "items": [
            {
                "skill_id": 1,
                "skill": "Python",
                "category": "language",
                "points": [
                    {
                        "ds": "2026-11-23",
                        "yhat": "3.5",
                        "yhat_lower": "1.0",
                        "yhat_upper": "5.0",
                        "model_version": "prophet-weekly-1",
                    }
                ],
            }
        ],
    }
    calls = _install(monkeypatch, payload)
    parsed = get_forecasts()
    assert calls[0]["url"] == "http://127.0.0.1:8000/skills/forecasts"
    assert calls[0]["params"] is None
    assert calls[0]["timeout"] == 10
    assert parsed["horizon_weeks"] == 8
    assert parsed["items"][0]["points"][0]["yhat"] == "3.5"

    calls.clear()
    assert get_forecasts(skill=" Python ")["items"][0]["skill"] == "Python"
    assert calls[0]["params"] == {"skill": "Python"}
    assert calls[0]["url"] == "http://127.0.0.1:8000/skills/forecasts"


def test_get_roles_url_params_and_parsing(monkeypatch):
    payload = {
        "items": [
            {
                "id": 1,
                "label": "Backend",
                "top_skills": ["Python", "SQL"],
                "job_count": 2,
                "run_at": "2026-11-20T09:00:00",
            }
        ]
    }
    calls = _install(monkeypatch, payload)
    parsed = get_roles()
    assert calls[0]["url"] == "http://127.0.0.1:8000/roles"
    assert calls[0]["params"] is None
    assert calls[0]["timeout"] == 10
    assert calls[0]["kwargs"] == {}
    assert parsed["items"][0]["label"] == "Backend"
    assert parsed["items"][0]["top_skills"] == ["Python", "SQL"]
    assert parsed["items"][0]["job_count"] == 2


def test_get_health_url_and_parsing(monkeypatch):
    calls = _install(monkeypatch, {"status": "ok"})
    assert get_health() == {"status": "ok"}
    assert calls[0]["url"] == "http://127.0.0.1:8000/health"
    assert calls[0]["params"] is None
    assert calls[0]["timeout"] == 10


def test_custom_base_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://localhost:9000/")
    calls = _install(monkeypatch, {"items": []})
    assert get_roles() == {"items": []}
    assert calls[0]["url"] == "http://localhost:9000/roles"
    assert calls[0]["timeout"] == 10


def test_missing_base_url_reads_project_dotenv(monkeypatch):
    seen: dict = {}

    def fake_dotenv(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return False

    monkeypatch.setattr("dashboard.api_client.load_dotenv", fake_dotenv)
    calls = _install(monkeypatch, {"status": "ok"})
    assert get_health() == {"status": "ok"}
    assert calls[0]["url"] == "http://127.0.0.1:8000/health"
    assert seen["args"] == (Path(__file__).resolve().parents[1] / ".env",)
    assert seen["kwargs"] == {}


def test_blank_base_url_uses_the_default(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "   ")
    calls = _install(monkeypatch, {"status": "ok"})
    assert get_health()["status"] == "ok"
    assert calls[0]["url"] == "http://127.0.0.1:8000/health"


@pytest.mark.parametrize(
    "error",
    [
        requests.ConnectionError("down"),
        requests.Timeout("slow"),
        requests.JSONDecodeError("Expecting value", "", 0),
    ],
)
def test_transport_errors_report_api_not_reachable(monkeypatch, error):
    def fake_get(url, params=None, timeout=None, **kwargs):
        raise error

    monkeypatch.setattr("dashboard.api_client.requests.get", fake_get)
    with pytest.raises(APIClientError, match="API not reachable") as caught:
        get_jobs()
    assert caught.value.__cause__ is error


def test_http_error_status_reports_api_not_reachable(monkeypatch):
    calls = _install(monkeypatch, {"detail": "unavailable"}, status_code=503)
    with pytest.raises(APIClientError, match="API not reachable") as caught:
        get_forecasts(skill="Python")
    assert calls[0]["url"] == "http://127.0.0.1:8000/skills/forecasts"
    assert calls[0]["params"] == {"skill": "Python"}
    assert calls[0]["timeout"] == 10
    assert isinstance(caught.value.__cause__, requests.HTTPError)


def test_non_object_json_reports_api_not_reachable(monkeypatch):
    _install(monkeypatch, ["not", "an", "object"])
    with pytest.raises(APIClientError, match="API not reachable"):
        get_trends(skill="Python", weeks=1)

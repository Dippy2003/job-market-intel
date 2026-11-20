"""Read-only API. TestClient against SQLite. No network and no Neon."""
from __future__ import annotations

import socket
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.deps import get_db
from api.main import create_app
from api.queries import as_text_list
from config import get_settings

ROOT = Path(__file__).resolve().parents[1]

SCHEMA = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    title_normalized TEXT,
    company TEXT,
    location TEXT,
    location_normalized TEXT,
    salary_min NUMERIC,
    salary_max NUMERIC,
    description TEXT,
    posted_date DATE,
    closing_date DATE,
    content_hash TEXT,
    raw_html_path TEXT,
    duplicate_of INTEGER,
    scraped_at DATETIME NOT NULL
);
CREATE TABLE skills (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT,
    aliases TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE job_skills (
    job_id INTEGER NOT NULL,
    skill_id INTEGER NOT NULL,
    method TEXT NOT NULL,
    confidence NUMERIC NOT NULL,
    PRIMARY KEY (job_id, skill_id)
);
CREATE TABLE skill_trends (
    skill_id INTEGER NOT NULL,
    period_start DATE NOT NULL,
    count INTEGER NOT NULL,
    share NUMERIC NOT NULL,
    PRIMARY KEY (skill_id, period_start)
);
CREATE TABLE forecasts (
    skill_id INTEGER NOT NULL,
    ds DATE NOT NULL,
    yhat NUMERIC NOT NULL,
    yhat_lower NUMERIC NOT NULL,
    yhat_upper NUMERIC NOT NULL,
    model_version TEXT NOT NULL,
    PRIMARY KEY (skill_id, ds, model_version)
);
CREATE TABLE role_clusters (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    top_skills TEXT NOT NULL,
    size INTEGER NOT NULL,
    run_at DATETIME NOT NULL
);
CREATE TABLE job_role_clusters (
    job_id INTEGER PRIMARY KEY,
    cluster_id INTEGER NOT NULL
);
"""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail the test if the API opens a socket or the configured engine."""

    def explode(*args, **kwargs):
        raise AssertionError("live network call")

    monkeypatch.setattr(socket, "create_connection", explode)


def _decimal(value) -> Decimal:
    return Decimal(str(value))


def _seed(conn) -> None:
    jobs = [
        {
            "id": 1,
            "source": "itpro",
            "url": "https://itpro.lk/jobs/1",
            "title": "Backend Engineer",
            "company": "Acme",
            "location": "Colombo",
            "description": "APIs and services",
            "salary_min": "100000.00",
            "salary_max": "150000.00",
            "posted_date": "2026-11-16",
            "duplicate_of": None,
            "scraped_at": "2026-11-18 09:00:00",
        },
        {
            "id": 2,
            "source": "topjobs",
            "url": "https://www.topjobs.lk/jobs/2",
            "title": "Frontend Developer",
            "company": "Northwind",
            "location": "Kandy",
            "description": "React interfaces",
            "salary_min": None,
            "salary_max": None,
            "posted_date": "2026-11-10",
            "duplicate_of": None,
            "scraped_at": "2026-11-17 09:00:00",
        },
        {
            "id": 3,
            "source": "itpro",
            "url": "https://itpro.lk/jobs/3",
            "title": "Java Developer",
            "company": "Acme",
            "location": "Galle",
            "description": "Spring services",
            "salary_min": None,
            "salary_max": None,
            "posted_date": "2026-11-12",
            "duplicate_of": None,
            "scraped_at": "2026-11-16 09:00:00",
        },
        {
            "id": 4,
            "source": "topjobs",
            "url": "https://www.topjobs.lk/jobs/4",
            "title": "Backend Engineer",
            "company": "Acme",
            "location": "Colombo",
            "description": "Same role posted twice",
            "salary_min": None,
            "salary_max": None,
            "posted_date": "2026-11-16",
            "duplicate_of": 1,
            "scraped_at": "2026-11-15 09:00:00",
        },
        {
            "id": 5,
            "source": "itpro",
            "url": "https://itpro.lk/jobs/5",
            "title": "Data Scientist",
            "company": "Lanka Analytics",
            "location": "Colombo",
            "description": "100% remote research role",
            "salary_min": None,
            "salary_max": None,
            "posted_date": "2026-11-18",
            "duplicate_of": None,
            "scraped_at": "2026-11-19 09:00:00",
        },
    ]
    conn.execute(
        text("""
            INSERT INTO jobs (
                id, source, url, title, company, location, description,
                salary_min, salary_max, posted_date, duplicate_of, scraped_at
            ) VALUES (
                :id, :source, :url, :title, :company, :location, :description,
                :salary_min, :salary_max, :posted_date, :duplicate_of, :scraped_at
            )
        """),
        jobs,
    )
    conn.execute(
        text("INSERT INTO skills (id, name, category) VALUES (:id, :name, :category)"),
        [
            {"id": 1, "name": "Python", "category": "language"},
            {"id": 2, "name": "SQL", "category": "database"},
            {"id": 3, "name": "JavaScript", "category": "frontend"},
            {"id": 4, "name": "Java", "category": "language"},
            {"id": 5, "name": "Pandas", "category": "data"},
        ],
    )
    conn.execute(
        text("""
            INSERT INTO job_skills (job_id, skill_id, method, confidence)
            VALUES (:job_id, :skill_id, 'spacy', '0.9500')
        """),
        [
            {"job_id": 1, "skill_id": 1},
            {"job_id": 1, "skill_id": 2},
            {"job_id": 2, "skill_id": 3},
            {"job_id": 3, "skill_id": 4},
            {"job_id": 5, "skill_id": 5},
        ],
    )
    conn.execute(
        text("""
            INSERT INTO skill_trends (skill_id, period_start, count, share)
            VALUES (:skill_id, :period_start, :count, :share)
        """),
        [
            {"skill_id": 1, "period_start": "2026-11-02", "count": 1, "share": "0.250000"},
            {"skill_id": 1, "period_start": "2026-11-09", "count": 2, "share": "0.500000"},
            {"skill_id": 1, "period_start": "2026-11-16", "count": 4, "share": "0.800000"},
            {"skill_id": 4, "period_start": "2026-11-09", "count": 1, "share": "0.250000"},
            {"skill_id": 3, "period_start": "2026-11-16", "count": 1, "share": "0.200000"},
        ],
    )
    forecast_start = date(2026, 11, 23)
    python_points = []
    for index in range(10):
        python_points.append(
            {
                "skill_id": 1,
                "ds": (forecast_start + timedelta(days=7 * index)).isoformat(),
                "yhat": f"{index + 1}.0000",
                "yhat_lower": f"{index}.0000",
                "yhat_upper": f"{index + 2}.0000",
                "model_version": "linear-fallback-1",
            }
        )
    newest = forecast_start + timedelta(days=7 * 9)
    python_points.append(
        {
            "skill_id": 1,
            "ds": newest.isoformat(),
            "yhat": "99.0000",
            "yhat_lower": "90.0000",
            "yhat_upper": "110.0000",
            "model_version": "prophet-weekly-1",
        }
    )
    java_points = [
        {
            "skill_id": 4,
            "ds": "2026-11-23",
            "yhat": "1.0000",
            "yhat_lower": "0.0000",
            "yhat_upper": "2.0000",
            "model_version": "linear-fallback-1",
        },
        {
            "skill_id": 4,
            "ds": "2026-11-30",
            "yhat": "2.0000",
            "yhat_lower": "1.0000",
            "yhat_upper": "3.0000",
            "model_version": "linear-fallback-1",
        },
    ]
    conn.execute(
        text("""
            INSERT INTO forecasts (skill_id, ds, yhat, yhat_lower, yhat_upper, model_version)
            VALUES (:skill_id, :ds, :yhat, :yhat_lower, :yhat_upper, :model_version)
        """),
        [*python_points, *java_points],
    )
    conn.execute(
        text("""
            INSERT INTO role_clusters (id, label, top_skills, size, run_at)
            VALUES (:id, :label, :top_skills, :size, :run_at)
        """),
        [
            {
                "id": 1,
                "label": "Backend",
                "top_skills": '{"SQL Server",Python}',
                "size": 2,
                "run_at": "2026-11-20 12:00:00",
            },
            {
                "id": 2,
                "label": "Frontend",
                "top_skills": "{JavaScript,React}",
                "size": 1,
                "run_at": "2026-11-20 12:00:00",
            },
        ],
    )
    conn.execute(
        text("INSERT INTO job_role_clusters (job_id, cluster_id) VALUES (:job_id, :cluster_id)"),
        [
            {"job_id": 1, "cluster_id": 1},
            {"job_id": 3, "cluster_id": 1},
            {"job_id": 2, "cluster_id": 2},
        ],
    )


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        for statement in SCHEMA.split(";"):
            sql = statement.strip()
            if sql:
                conn.exec_driver_sql(sql)
        _seed(conn)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    def refuse_configured_engine():
        raise AssertionError("API test tried to open DATABASE_URL")

    monkeypatch.setattr("api.deps.get_engine", refuse_configured_engine)
    application = create_app()
    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()


def test_health_openapi_and_docs(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert set(paths) >= {
        "/health",
        "/jobs",
        "/skills/trends",
        "/skills/forecasts",
        "/roles",
        "/roles/{id}",
    }
    job_params = {item["name"] for item in paths["/jobs"]["get"]["parameters"]}
    assert {"source", "q", "skill", "limit", "offset"} <= job_params
    trend_params = {item["name"] for item in paths["/skills/trends"]["get"]["parameters"]}
    assert {"skill", "weeks"} <= trend_params
    assert "postgresql://" not in spec.text
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "text/html" in docs.headers["content-type"]
    redoc = client.get("/redoc")
    assert redoc.status_code == 200
    assert client.post("/jobs").status_code == 405


def test_jobs_filters_and_pagination(client):
    page = client.get("/jobs", params={"limit": 1, "offset": 1})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 5
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert [item["id"] for item in body["items"]] == [1]
    assert body["items"][0]["skills"] == ["Python", "SQL"]
    assert _decimal(body["items"][0]["salary_min"]) == Decimal("100000.00")
    assert body["items"][0]["duplicate_of"] is None

    newest = client.get("/jobs", params={"limit": 1}).json()
    assert newest["items"][0]["id"] == 5

    topjobs = client.get("/jobs", params={"source": "TOPJOBS"}).json()
    assert topjobs["total"] == 2
    assert [item["id"] for item in topjobs["items"]] == [2, 4]
    assert topjobs["items"][1]["duplicate_of"] == 1

    java = client.get("/jobs", params={"skill": "java"}).json()
    assert [item["id"] for item in java["items"]] == [3]
    javascript = client.get("/jobs", params={"skill": "JavaScript"}).json()
    assert [item["id"] for item in javascript["items"]] == [2]

    pandas = client.get("/jobs", params={"skill": "pandas"}).json()
    assert [item["id"] for item in pandas["items"]] == [5]
    assert client.get("/jobs", params={"q": "pandas"}).json()["total"] == 0

    combined = client.get("/jobs", params={"source": "itpro", "skill": "Python"}).json()
    assert [item["id"] for item in combined["items"]] == [1]
    titled = client.get("/jobs", params={"source": "itpro", "q": "backend"}).json()
    assert [item["id"] for item in titled["items"]] == [1]
    colombo = client.get("/jobs", params={"q": "Colombo"}).json()
    assert [item["id"] for item in colombo["items"]] == [5, 1, 4]
    assert client.get("/jobs", params={"skill": "missing"}).json()["total"] == 0
    assert client.get("/jobs", params={"q": "   "}).json()["total"] == 5
    beyond = client.get("/jobs", params={"limit": 10, "offset": 20}).json()
    assert beyond["items"] == []
    assert beyond["total"] == 5


def test_text_query_treats_percent_as_literal(client):
    matched = client.get("/jobs", params={"q": "%"}).json()
    assert matched["total"] == 1
    assert matched["items"][0]["id"] == 5
    assert client.get("/jobs", params={"q": "northwind"}).json()["items"][0]["id"] == 2
    assert client.get("/jobs", params={"q": "galle"}).json()["items"][0]["title"] == "Java Developer"


def test_trends_filter_by_skill_and_weeks(client):
    all_rows = client.get("/skills/trends").json()
    python = next(item for item in all_rows["items"] if item["skill"] == "Python")
    assert [point["period_start"] for point in python["points"]] == [
        "2026-11-02",
        "2026-11-09",
        "2026-11-16",
    ]
    assert python["points"][-1]["count"] == 4
    assert _decimal(python["points"][-1]["share"]) == Decimal("0.800000")
    assert python["category"] == "language"

    recent = client.get("/skills/trends", params={"weeks": 2}).json()
    by_name = {item["skill"]: item for item in recent["items"]}
    assert set(by_name) == {"Java", "JavaScript", "Python"}
    assert [point["period_start"] for point in by_name["Python"]["points"]] == [
        "2026-11-09",
        "2026-11-16",
    ]
    one = client.get("/skills/trends", params={"skill": "PYTHON", "weeks": 1}).json()
    assert len(one["items"]) == 1
    assert one["items"][0]["points"] == [
        {"period_start": "2026-11-16", "count": 4, "share": one["items"][0]["points"][0]["share"]}
    ]
    assert _decimal(one["items"][0]["points"][0]["share"]) == Decimal("0.8")
    assert client.get("/skills/trends", params={"skill": "Rust"}).json() == {"items": []}


def test_forecasts_keep_eight_weeks_per_skill(client):
    body = client.get("/skills/forecasts").json()
    assert body["horizon_weeks"] == 8
    by_name = {item["skill"]: item for item in body["items"]}
    assert set(by_name) == {"Java", "Python"}
    java_dates = [point["ds"] for point in by_name["Java"]["points"]]
    assert java_dates == ["2026-11-23", "2026-11-30"]
    python_dates = [point["ds"] for point in by_name["Python"]["points"]]
    assert "2026-11-23" not in python_dates
    assert "2026-11-30" not in python_dates
    assert len(set(python_dates)) == 8
    assert python_dates[-1] == "2027-01-25"
    versions = {
        point["model_version"]
        for point in by_name["Python"]["points"]
        if point["ds"] == "2027-01-25"
    }
    assert versions == {"linear-fallback-1", "prophet-weekly-1"}
    only_java = client.get("/skills/forecasts", params={"skill": "Java"}).json()
    assert [item["skill"] for item in only_java["items"]] == ["Java"]
    assert client.get("/skills/forecasts", params={"skill": "Pandas"}).json()["items"] == []


def test_roles_list_detail_and_missing(client):
    listing = client.get("/roles").json()
    assert [item["label"] for item in listing["items"]] == ["Backend", "Frontend"]
    assert listing["items"][0]["job_count"] == 2
    assert listing["items"][0]["top_skills"] == ["SQL Server", "Python"]
    assert listing["items"][1]["top_skills"] == ["JavaScript", "React"]
    assert listing["items"][0]["run_at"].startswith("2026-11-20")

    detail = client.get("/roles/1")
    assert detail.status_code == 200
    body = detail.json()
    assert body["label"] == "Backend"
    assert [job["title"] for job in body["jobs"]] == ["Backend Engineer", "Java Developer"]
    assert body["jobs"][0]["source"] == "itpro"
    frontend = client.get("/roles/2").json()
    assert [job["id"] for job in frontend["jobs"]] == [2]
    missing = client.get("/roles/99")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Role not found"


def test_invalid_query_parameters_are_rejected(client):
    assert client.get("/jobs", params={"limit": 0}).status_code == 422
    assert client.get("/jobs", params={"limit": 101}).status_code == 422
    assert client.get("/jobs", params={"offset": -1}).status_code == 422
    assert client.get("/skills/trends", params={"weeks": 0}).status_code == 422
    assert client.get("/roles/abc").status_code == 422


def test_cors_origins_come_from_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, http://127.0.0.1:5173")
    get_settings.cache_clear()
    try:
        application = create_app()
        with TestClient(application) as test_client:
            allowed = test_client.get("/health", headers={"Origin": "http://localhost:3000"})
            assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
            blocked = test_client.get("/health", headers={"Origin": "https://example.com"})
            assert "access-control-allow-origin" not in blocked.headers
    finally:
        get_settings.cache_clear()

    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    get_settings.cache_clear()
    try:
        application = create_app()
        with TestClient(application) as test_client:
            response = test_client.get("/health", headers={"Origin": "https://example.com"})
            assert response.headers["access-control-allow-origin"] == "*"
    finally:
        get_settings.cache_clear()


def test_session_dependency_uses_the_configured_engine(monkeypatch):
    source = (ROOT / "api" / "deps.py").read_text(encoding="utf-8")
    engine_source = (ROOT / "db" / "__init__.py").read_text(encoding="utf-8")
    assert "get_engine" in source
    assert "get_settings().database_url" in engine_source
    assert "os.environ" not in source
    engine = create_engine("sqlite://", poolclass=StaticPool)
    monkeypatch.setattr("api.deps.get_engine", lambda: engine)
    dependency = get_db()
    session = next(dependency)
    try:
        assert session.get_bind() is engine
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        dependency.close()


def test_text_array_parser_accepts_postgres_literals():
    assert as_text_list(None) == []
    assert as_text_list(["Java", "SQL"]) == ["Java", "SQL"]
    assert as_text_list("{}") == []
    assert as_text_list("{Java,PostgreSQL}") == ["Java", "PostgreSQL"]
    assert as_text_list('{"SQL Server",Python}') == ["SQL Server", "Python"]
    assert as_text_list('{"a,b",c}') == ["a,b", "c"]
    assert as_text_list('{"a\\"b"}') == ['a"b']
    with pytest.raises(ValueError):
        as_text_list("Python")


def test_forecast_dates_used_by_the_fixture_are_mondays():
    assert date(2026, 11, 23).strftime("%A") == "Monday"
    assert datetime(2026, 11, 20).strftime("%A") == "Friday"

"""Role clustering. Fixtures and an in-memory database. No live network calls."""
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from analytics.clusters import MIN_JOBS, ClusterJob, build_role_clusters
from pipeline.cluster_roles import FETCH_CLUSTER_JOBS_SQL, build_parser, cluster_roles, render_report

ROOT = Path(__file__).resolve().parents[1]
GROUPS = json.loads((ROOT / "tests" / "fixtures" / "role_jobs.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail the test if clustering opens a connection."""

    def explode(*args, **kwargs):
        raise AssertionError("live network call")

    monkeypatch.setattr(socket, "create_connection", explode)


def _fixture_jobs():
    jobs = []
    job_id = 1
    by_role = {}
    for group in GROUPS:
        ids = []
        skills = tuple(skill["name"] for skill in group["skills"])
        categories = tuple(skill["category"] for skill in group["skills"])
        for _ in range(group["count"]):
            jobs.append(ClusterJob(job_id, group["title"], skills, categories))
            ids.append(job_id)
            job_id += 1
        by_role[group["role"]] = tuple(ids)
    return jobs, by_role


def _rows_for(jobs, extra=()):
    rows = []
    for job in jobs:
        if not job.skills:
            rows.append(_Row(job_id=job.job_id, title=job.title, skill_name=None, category=None))
            continue
        for skill, category in zip(job.skills, job.categories, strict=True):
            rows.append(_Row(job_id=job.job_id, title=job.title, skill_name=skill, category=category))
    rows.extend(extra)
    return rows


class _Result:
    def __init__(self, rows, rowcount=0):
        self._rows = rows
        self.rowcount = rowcount

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._rows[0].id


class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Store:
    def __init__(self, rows, clusters=None, assignments=None):
        self.rows = rows
        self.clusters = list(clusters or [])
        self.assignments = list(assignments or [])
        self.statements = []
        self._next_id = 1 + max((cluster["id"] for cluster in self.clusters), default=0)

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = dict(params or {})
        self.statements.append((sql, params))
        if "FROM jobs" in sql:
            return _Result(self.rows)
        if sql.startswith("DELETE FROM job_role_clusters"):
            removed = len(self.assignments)
            self.assignments = []
            return _Result([], rowcount=removed)
        if sql.startswith("DELETE FROM role_clusters"):
            removed = len(self.clusters)
            self.clusters = []
            return _Result([], rowcount=removed)
        if "INSERT INTO role_clusters" in sql:
            new_id = self._next_id
            self._next_id += 1
            self.clusters.append(
                {
                    "id": new_id,
                    "label": params["label"],
                    "top_skills": params["top_skills"],
                    "size": params["size"],
                    "run_at": params["run_at"],
                }
            )
            return _Result([_Row(id=new_id)])
        if "INSERT INTO job_role_clusters" in sql:
            self.assignments.append((params["job_id"], params["cluster_id"]))
            return _Result([])
        raise AssertionError(f"unexpected SQL: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Engine:
    def __init__(self, store):
        self.store = store
        self.began = 0
        self.connected = 0

    def begin(self):
        self.began += 1
        return self.store

    def connect(self):
        self.connected += 1
        return self.store


def _engine(monkeypatch, store):
    engine = _Engine(store)
    monkeypatch.setattr("pipeline.cluster_roles.get_engine", lambda: engine)
    return engine


def _membership(store):
    by_id = {cluster["id"]: cluster["label"] for cluster in store.clusters}
    grouped = {}
    for job_id, cluster_id in store.assignments:
        grouped.setdefault(by_id[cluster_id], set()).add(job_id)
    return grouped


def test_fixture_separates_role_families_and_is_deterministic():
    jobs, by_role = _fixture_jobs()
    first = build_role_clusters(jobs, k=6)
    second = build_role_clusters(jobs, k=6)
    assert first == second
    assert first.too_few is False
    assert first.k_used == 6
    assert first.jobs == 24
    assert len(first.clusters) == 6
    found = {}
    for cluster in first.clusters:
        assert cluster.size == 4
        matching = [role for role, ids in by_role.items() if ids == cluster.job_ids]
        assert matching, cluster.job_ids
        found[matching[0]] = cluster.label
    assert found == {
        "Backend": "Backend",
        "Frontend": "Frontend",
        "Data/ML": "Data/ML",
        "DevOps": "DevOps",
        "QA": "QA",
        "Mobile": "Mobile",
    }
    assert [cluster.label for cluster in first.clusters] == [
        "Backend",
        "Data/ML",
        "DevOps",
        "Frontend",
        "Mobile",
        "QA",
    ]
    backend = next(cluster for cluster in first.clusters if cluster.label == "Backend")
    assert backend.top_skills == ("Java", "PostgreSQL", "Spring")
    assert backend.top_titles == ("Backend Engineer",)


def test_titles_split_jobs_that_share_skills():
    backend = [
        ClusterJob(job_id, "Backend Engineer", ("Python", "SQL"), ("language", "language"))
        for job_id in range(1, 4)
    ]
    data = [
        ClusterJob(job_id, "Data Scientist", ("Python", "SQL"), ("language", "language"))
        for job_id in range(4, 7)
    ]
    build = build_role_clusters([*backend, *data], k=2)
    assert {cluster.label for cluster in build.clusters} == {"Backend", "Data/ML"}
    assert {cluster.job_ids for cluster in build.clusters} == {(1, 2, 3), (4, 5, 6)}


def test_same_role_is_split_by_its_top_skill():
    java = [
        ClusterJob(job_id, "Backend Engineer", ("Java", "Spring"), ("language", "backend"))
        for job_id in range(1, 5)
    ]
    dotnet = [
        ClusterJob(job_id, "Backend Engineer", ("C#", ".NET"), ("language", "backend"))
        for job_id in range(5, 9)
    ]
    build = build_role_clusters([*java, *dotnet], k=2)
    assert {cluster.job_ids for cluster in build.clusters} == {(1, 2, 3, 4), (5, 6, 7, 8)}
    assert {cluster.label for cluster in build.clusters} == {"Backend · Java", "Backend · .NET"}


def test_unknown_skills_are_labeled_from_their_names():
    jobs = [
        ClusterJob(1, "Widget Maker", ("Zorblax", "Quux")),
        ClusterJob(2, "Widget Maker", ("Zorblax", "Quux")),
    ]
    build = build_role_clusters(jobs, k=4)
    assert build.too_few is False
    assert build.k_requested == 4
    assert build.k_used == 1
    assert build.profiles == 1
    assert build.clusters[0].label == "Quux / Zorblax"
    assert build.clusters[0].job_ids == (1, 2)
    report = render_report(build, skipped=0, dry_run=True, removed=0)
    assert "Requested k=4. Using 1 (1 distinct skill profile among 2 jobs)." in report
    assert report.endswith("Dry run: nothing was written.")


def test_tied_frontend_and_backend_is_labeled_full_stack():
    jobs = [
        ClusterJob(job_id, "Full-Stack Engineer", ("React", "Django"), ("frontend", "backend"))
        for job_id in (1, 2)
    ]
    build = build_role_clusters(jobs, k=2)
    assert len(build.clusters) == 1
    assert build.clusters[0].label == "Full Stack"
    assert build.clusters[0].job_ids == (1, 2)


def test_taxonomy_category_labels_a_cluster_when_the_row_has_none():
    jobs = [
        ClusterJob(1, "Engineer", ("Django", "PostgreSQL")),
        ClusterJob(2, "Engineer", ("Django", "PostgreSQL")),
    ]
    build = build_role_clusters(jobs, k=2)
    assert build.clusters[0].label == "Backend"
    assert build.clusters[0].top_skills[0] == "Django"


def test_too_few_jobs_do_not_raise():
    assert build_role_clusters([], k=6).too_few is True
    one = build_role_clusters([ClusterJob(1, "Backend Engineer", ("Java",))], k=6)
    assert one.too_few is True
    assert one.jobs == 1
    assert one.clusters == ()
    assert one.k_used == 0
    with pytest.raises(ValueError):
        build_role_clusters([], k=0)


def test_dry_run_prints_the_clusters_and_writes_nothing(monkeypatch):
    jobs, _by_role = _fixture_jobs()
    skipped = ClusterJob(100, "Office Administrator", ())
    stale = [{"id": 7, "label": "Stale", "top_skills": "{}", "size": 1, "run_at": None}]
    store = _Store(_rows_for([*jobs, skipped]), clusters=stale, assignments=[(1, 7)])
    engine = _engine(monkeypatch, store)
    summary = cluster_roles(dry_run=True, k=6)
    assert engine.connected == 1
    assert engine.began == 0
    assert store.clusters == stale
    assert store.assignments == [(1, 7)]
    assert not any("INSERT" in sql or "DELETE" in sql for sql, _params in store.statements)
    assert "duplicate_of IS NULL" in str(FETCH_CLUSTER_JOBS_SQL)
    assert "LEFT JOIN" in str(FETCH_CLUSTER_JOBS_SQL)
    assert summary["dry_run"] is True
    assert summary["jobs"] == 24
    assert summary["skipped"] == 1
    assert summary["too_few"] is False
    assert summary["removed"] == 0
    assert [cluster["label"] for cluster in summary["clusters"]] == [
        "Backend",
        "Data/ML",
        "DevOps",
        "Frontend",
        "Mobile",
        "QA",
    ]
    assert summary["report"] == "\n".join(
        [
            "Role clusters (k=6, 24 jobs):",
            " 1. Backend  size=4  skills=Java, PostgreSQL, Spring  titles=Backend Engineer",
            " 2. Data/ML  size=4  skills=Pandas, Python, TensorFlow  titles=Data Scientist",
            " 3. DevOps  size=4  skills=Docker, Kubernetes, Terraform  titles=DevOps Engineer",
            " 4. Frontend  size=4  skills=CSS, React, TypeScript  titles=Frontend Developer",
            " 5. Mobile  size=4  skills=Android, Flutter, Kotlin  titles=Android Developer",
            " 6. QA  size=4  skills=Cypress, JUnit, Selenium  titles=QA Engineer",
            "Model: binary TF-IDF, KMeans, random_state=42.",
            "Skipped 1 job with no extracted skills.",
            "Dry run: nothing was written.",
        ]
    )


def test_write_replaces_previous_clusters(monkeypatch):
    jobs, by_role = _fixture_jobs()
    store = _Store(
        _rows_for(jobs),
        clusters=[{"id": 3, "label": "Old", "top_skills": "{}", "size": 9, "run_at": None}],
        assignments=[(1, 3), (2, 3)],
    )
    engine = _engine(monkeypatch, store)
    summary = cluster_roles(k=6)
    assert engine.began == 1
    assert summary["removed"] == 1
    assert "Replaced 1 previous cluster." in summary["report"]
    assert len(store.clusters) == 6
    assert len({cluster["run_at"] for cluster in store.clusters}) == 1
    assert all(cluster["size"] == 4 for cluster in store.clusters)
    membership = _membership(store)
    assert membership["Backend"] == set(by_role["Backend"])
    assert set().union(*membership.values()) == set(range(1, 25))
    sql = "\n".join(statement for statement, _params in store.statements)
    assert "DELETE FROM job_role_clusters" in sql
    assert "DELETE FROM role_clusters" in sql
    assert "INSERT INTO role_clusters" in sql
    assert "CAST(:top_skills AS text[])" in sql
    assert "INSERT INTO job_role_clusters" in sql
    assert '"Java"' in store.clusters[0]["top_skills"]

    again = cluster_roles(k=6)
    assert again["removed"] == 6
    assert _membership(store) == membership
    assert engine.began == 2


def test_too_few_jobs_clear_stored_clusters_without_raising(monkeypatch):
    store = _Store(
        [_Row(job_id=1, title="Backend Engineer", skill_name="Java", category="language")],
        clusters=[{"id": 4, "label": "Old", "top_skills": "{}", "size": 1, "run_at": None}],
        assignments=[(1, 4)],
    )
    _engine(monkeypatch, store)
    summary = cluster_roles(k=6)
    assert summary["too_few"] is True
    assert summary["jobs"] == 1
    assert summary["clusters"] == []
    assert summary["removed"] == 1
    assert store.clusters == []
    assert store.assignments == []
    assert summary["report"] == "\n".join(
        [
            f"Too few jobs to cluster: 1 with skills, need at least {MIN_JOBS}.",
            "Removed 1 stored cluster.",
        ]
    )

    empty = cluster_roles(dry_run=True, k=6)
    assert empty["removed"] == 0
    assert "Dry run: nothing was written." in empty["report"]
    assert store.clusters == []


def test_k_must_be_positive():
    with pytest.raises(ValueError):
        cluster_roles(k=0)


def test_cli_help_and_flags():
    parser = build_parser()
    defaults = parser.parse_args([])
    assert defaults.dry_run is False
    assert defaults.k == 6
    selected = parser.parse_args(["--dry-run", "--k", "4"])
    assert selected.dry_run is True
    assert selected.k == 4
    with pytest.raises(SystemExit):
        parser.parse_args(["--k", "0"])
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.cluster_roles", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout
    assert "--k" in result.stdout

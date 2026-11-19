"""ORM models and Alembic revisions. No database connection."""
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import CheckConstraint

from db import Base
from db.models import Forecast, Job, JobSkill, RoleCluster, ScrapeRun, Skill, SkillTrend

ROOT = Path(__file__).resolve().parents[1]

EXPECTED = {
    Job: "jobs",
    ScrapeRun: "scrape_runs",
    Skill: "skills",
    JobSkill: "job_skills",
    SkillTrend: "skill_trends",
    Forecast: "forecasts",
    RoleCluster: "role_clusters",
}


def test_model_table_names():
    for model, name in EXPECTED.items():
        assert model.__tablename__ == name
    assert set(Base.metadata.tables) == set(EXPECTED.values())


def test_skill_name_is_unique_and_job_skill_key_is_composite():
    assert Skill.__table__.c.name.unique is True
    assert [column.name for column in JobSkill.__table__.primary_key] == ["job_id", "skill_id"]
    assert [column.name for column in SkillTrend.__table__.primary_key] == ["skill_id", "period_start"]
    assert [column.name for column in Forecast.__table__.primary_key] == ["skill_id", "ds", "model_version"]
    checks = [c.sqltext.text for c in JobSkill.__table__.constraints if isinstance(c, CheckConstraint)]
    assert any("spacy" in text and "llm" in text for text in checks)


def test_foreign_keys_point_at_parent_ids():
    def links(table):
        return {(fk.parent.name, fk.column.table.name, fk.column.name) for fk in table.foreign_keys}

    assert links(JobSkill.__table__) == {("job_id", "jobs", "id"), ("skill_id", "skills", "id")}
    assert links(SkillTrend.__table__) == {("skill_id", "skills", "id")}
    assert links(Forecast.__table__) == {("skill_id", "skills", "id")}
    assert links(RoleCluster.__table__) == set()


def test_alembic_env_reads_settings_url():
    source = (ROOT / "db" / "alembic" / "env.py").read_text(encoding="utf-8")
    ini = (ROOT / "alembic.ini").read_text(encoding="utf-8")
    assert "get_settings().database_url" in source
    assert "target_metadata = Base.metadata" in source
    url_line = next(line for line in ini.splitlines() if line.startswith("sqlalchemy.url"))
    assert "@" not in url_line
    assert "neon" not in ini.lower()


def test_offline_sql_builds_every_table_without_a_database():
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://u:p@localhost/db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0002", "--sql"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    sql = result.stdout.lower()
    for name in EXPECTED.values():
        assert f"create table {name}" in sql
    assert "location_normalized" in sql
    assert "duplicate_of" in sql
    assert "generated always as identity" in sql
    assert "job_skills_method_chk" in sql

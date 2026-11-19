"""ORM models for jobs, scraper runs, skills, and forecasts."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class Job(Base):
    """One scraped job posting. url is unique across sources."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("jobs_content_hash_idx", "content_hash"),
        Index("jobs_source_scraped_at_idx", "source", desc("scraped_at")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    title_normalized: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    location_normalized: Mapped[str | None] = mapped_column(Text)
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    description: Mapped[str | None] = mapped_column(Text)
    posted_date: Mapped[date | None] = mapped_column(Date)
    closing_date: Mapped[date | None] = mapped_column(Date)
    content_hash: Mapped[str | None] = mapped_column(Text)
    raw_html_path: Mapped[str | None] = mapped_column(Text)
    duplicate_of: Mapped[int | None] = mapped_column(BigInteger)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScrapeRun(Base):
    """One execution of a scraper, with page and insert counts."""

    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pages: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    found: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    inserted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(Text, default="running", server_default=text("'running'"))


class Skill(Base):
    """A normalized skill name, with an optional category and alternate names."""

    __tablename__ = "skills"
    __table_args__ = (Index("skills_category_idx", "category"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    category: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )


class JobSkill(Base):
    """A skill extracted from one job. method is spacy or llm. confidence is 0 to 1."""

    __tablename__ = "job_skills"
    __table_args__ = (
        CheckConstraint("method IN ('spacy', 'llm')", name="job_skills_method_chk"),
        Index("job_skills_skill_id_idx", "skill_id"),
    )

    job_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )
    method: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))


class SkillTrend(Base):
    """One skill's count and share of postings for a period starting on period_start."""

    __tablename__ = "skill_trends"
    __table_args__ = (Index("skill_trends_period_start_idx", "period_start"),)

    skill_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )
    period_start: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    share: Mapped[Decimal] = mapped_column(Numeric(7, 6))


class Forecast(Base):
    """A forecast point for one skill, date, and model version."""

    __tablename__ = "forecasts"
    __table_args__ = (Index("forecasts_ds_idx", "ds"),)

    skill_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ds: Mapped[date] = mapped_column(Date, primary_key=True)
    yhat: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    yhat_lower: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    yhat_upper: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    model_version: Mapped[str] = mapped_column(Text, primary_key=True)


class RoleCluster(Base):
    """Roles grouped by one clustering run. top_skills lists skill names, best first."""

    __tablename__ = "role_clusters"
    __table_args__ = (Index("role_clusters_run_at_idx", "run_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    top_skills: Mapped[list[str]] = mapped_column(ARRAY(Text))
    size: Mapped[int] = mapped_column(Integer)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

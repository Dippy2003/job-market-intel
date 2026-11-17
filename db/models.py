"""ORM models for jobs and scraper runs."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Identity, Index, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class Job(Base):
    """One scraped job posting. url is unique across sources."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("jobs_content_hash_idx", "content_hash"),
        Index("jobs_source_scraped_at_idx", "source", "scraped_at"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
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

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pages: Mapped[int] = mapped_column(default=0, server_default="0")
    found: Mapped[int] = mapped_column(default=0, server_default="0")
    inserted: Mapped[int] = mapped_column(default=0, server_default="0")
    errors: Mapped[int] = mapped_column(default=0, server_default="0")
    status: Mapped[str] = mapped_column(Text, default="running", server_default="running")

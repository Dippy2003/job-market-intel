"""Baseline jobs and scrape_runs tables.

Matches db/migrations/001_jobs_and_scrape_runs.sql plus the columns added by
002_clean_columns.sql. Stamp this revision on a database that already has
those tables (`alembic stamp 0001`) instead of running this upgrade there.

Revision ID: 0001
Revises:
Create Date: 2026-11-19
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_normalized", sa.Text(), nullable=True),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("salary_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("salary_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("posted_date", sa.Date(), nullable=True),
        sa.Column("closing_date", sa.Date(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("raw_html_path", sa.Text(), nullable=True),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("location_normalized", sa.Text(), nullable=True),
        sa.Column("duplicate_of", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("url", name="jobs_url_key"),
    )
    op.create_index("jobs_content_hash_idx", "jobs", ["content_hash"])
    op.create_index(
        "jobs_source_scraped_at_idx",
        "jobs",
        ["source", sa.text("scraped_at DESC")],
    )
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("found", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("inserted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("errors", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
    )


def downgrade() -> None:
    op.drop_table("scrape_runs")
    op.drop_index("jobs_source_scraped_at_idx", table_name="jobs")
    op.drop_index("jobs_content_hash_idx", table_name="jobs")
    op.drop_table("jobs")

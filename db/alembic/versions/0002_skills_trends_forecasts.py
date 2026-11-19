"""Skills, job links, trends, forecasts, and role clusters.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column(
            "aliases",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.UniqueConstraint("name", name="skills_name_key"),
    )
    op.create_index("skills_category_idx", "skills", ["category"])
    op.create_table(
        "job_skills",
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("skill_id", sa.BigInteger(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.CheckConstraint("method IN ('spacy', 'llm')", name="job_skills_method_chk"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="job_skills_job_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name="job_skills_skill_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id", "skill_id", name="job_skills_pkey"),
    )
    op.create_index("job_skills_skill_id_idx", "job_skills", ["skill_id"])
    op.create_table(
        "skill_trends",
        sa.Column("skill_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("share", sa.Numeric(7, 6), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name="skill_trends_skill_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("skill_id", "period_start", name="skill_trends_pkey"),
    )
    op.create_index("skill_trends_period_start_idx", "skill_trends", ["period_start"])
    op.create_table(
        "forecasts",
        sa.Column("skill_id", sa.BigInteger(), nullable=False),
        sa.Column("ds", sa.Date(), nullable=False),
        sa.Column("yhat", sa.Numeric(14, 4), nullable=False),
        sa.Column("yhat_lower", sa.Numeric(14, 4), nullable=False),
        sa.Column("yhat_upper", sa.Numeric(14, 4), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name="forecasts_skill_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("skill_id", "ds", "model_version", name="forecasts_pkey"),
    )
    op.create_index("forecasts_ds_idx", "forecasts", ["ds"])
    op.create_table(
        "role_clusters",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("top_skills", ARRAY(sa.Text()), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("role_clusters_run_at_idx", "role_clusters", ["run_at"])


def downgrade() -> None:
    op.drop_index("role_clusters_run_at_idx", table_name="role_clusters")
    op.drop_table("role_clusters")
    op.drop_index("forecasts_ds_idx", table_name="forecasts")
    op.drop_table("forecasts")
    op.drop_index("skill_trends_period_start_idx", table_name="skill_trends")
    op.drop_table("skill_trends")
    op.drop_index("job_skills_skill_id_idx", table_name="job_skills")
    op.drop_table("job_skills")
    op.drop_index("skills_category_idx", table_name="skills")
    op.drop_table("skills")

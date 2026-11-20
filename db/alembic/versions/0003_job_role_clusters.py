"""Job membership for role clusters.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_role_clusters",
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("cluster_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="job_role_clusters_job_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["role_clusters.id"],
            name="job_role_clusters_cluster_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id", name="job_role_clusters_pkey"),
    )
    op.create_index("job_role_clusters_cluster_id_idx", "job_role_clusters", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("job_role_clusters_cluster_id_idx", table_name="job_role_clusters")
    op.drop_table("job_role_clusters")

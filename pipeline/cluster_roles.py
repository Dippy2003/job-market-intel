"""Group jobs into role clusters and store the latest run.

Reads non-duplicate jobs, clusters those that have extracted skills, and
replaces ``role_clusters`` plus ``job_role_clusters``. Prints one line per
cluster. Re-running replaces the previous run. Jobs with no skills, and
duplicate postings, are left out of the fit.

    python -m pipeline.cluster_roles
    python -m pipeline.cluster_roles --k 8
    python -m pipeline.cluster_roles --dry-run
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text

from analytics.clusters import (
    DEFAULT_K,
    MIN_JOBS,
    RANDOM_STATE,
    ClusterBuild,
    ClusterJob,
    build_role_clusters,
)
from config import setup_logging
from db import get_engine

log = logging.getLogger(__name__)

FETCH_CLUSTER_JOBS_SQL = text("""
SELECT
    j.id AS job_id,
    j.title AS title,
    s.name AS skill_name,
    s.category AS category
FROM jobs AS j
LEFT JOIN job_skills AS js ON js.job_id = j.id
LEFT JOIN skills AS s ON s.id = js.skill_id
WHERE j.duplicate_of IS NULL
ORDER BY j.id, s.name
""")

DELETE_ASSIGNMENTS_SQL = text("DELETE FROM job_role_clusters")

DELETE_CLUSTERS_SQL = text("DELETE FROM role_clusters")

# CAST, not ::, so SQLAlchemy does not treat ::text[] as a bind parameter.
INSERT_CLUSTER_SQL = text("""
INSERT INTO role_clusters (label, top_skills, size, run_at)
VALUES (:label, CAST(:top_skills AS text[]), :size, :run_at)
RETURNING id
""")

INSERT_ASSIGNMENT_SQL = text("""
INSERT INTO job_role_clusters (job_id, cluster_id)
VALUES (:job_id, :cluster_id)
""")


def pg_text_array(values: list[str]) -> str:
    """Format values as a Postgres text[] literal. Quotes and backslashes are escaped."""
    parts: list[str] = []
    for value in values:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        parts.append('"' + escaped + '"')
    return "{" + ",".join(parts) + "}"


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("--k must be a positive integer")
    return number


def _count_phrase(count: int, singular: str) -> str:
    word = singular if count == 1 else singular + "s"
    return f"{count} {word}"


@dataclass
class _JobBucket:
    title: str
    skills: list[str]
    categories: list[str | None]


def jobs_from_rows(rows) -> tuple[list[ClusterJob], int]:
    """Collapse skill rows into jobs. Jobs with no skill name are counted as skipped."""
    grouped: dict[int, _JobBucket] = {}
    order: list[int] = []
    for row in rows:
        job_id = int(row.job_id)
        bucket = grouped.get(job_id)
        if bucket is None:
            bucket = _JobBucket(title=str(row.title or ""), skills=[], categories=[])
            grouped[job_id] = bucket
            order.append(job_id)
        name = getattr(row, "skill_name", None)
        if not name:
            continue
        bucket.skills.append(str(name))
        category = getattr(row, "category", None)
        bucket.categories.append(str(category) if category else None)
    jobs: list[ClusterJob] = []
    skipped = 0
    for job_id in order:
        bucket = grouped[job_id]
        if not bucket.skills:
            skipped += 1
            continue
        seen: set[str] = set()
        unique_skills: list[str] = []
        unique_categories: list[str | None] = []
        for skill, category in zip(bucket.skills, bucket.categories, strict=True):
            key = skill.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique_skills.append(skill)
            unique_categories.append(category)
        jobs.append(ClusterJob(job_id, bucket.title, tuple(unique_skills), tuple(unique_categories)))
    return jobs, skipped


def render_report(build: ClusterBuild, *, skipped: int, dry_run: bool, removed: int) -> str:
    """Text block the CLI prints."""
    lines: list[str] = []
    if build.too_few:
        lines.append(
            f"Too few jobs to cluster: {build.jobs} with skills, need at least {MIN_JOBS}."
        )
    else:
        lines.append(f"Role clusters (k={build.k_used}, {_count_phrase(build.jobs, 'job')}):")
        if build.k_used != build.k_requested:
            lines.append(
                f"Requested k={build.k_requested}. "
                f"Using {build.k_used} "
                f"({_count_phrase(build.profiles, 'distinct skill profile')} "
                f"among {_count_phrase(build.jobs, 'job')})."
            )
        for index, cluster in enumerate(build.clusters, start=1):
            skills = ", ".join(cluster.top_skills) if cluster.top_skills else "-"
            titles = ", ".join(cluster.top_titles) if cluster.top_titles else "-"
            lines.append(
                f"{index:>2}. {cluster.label}  size={cluster.size}  skills={skills}  titles={titles}"
            )
        lines.append(f"Model: binary TF-IDF, KMeans, random_state={RANDOM_STATE}.")
    if skipped:
        lines.append(f"Skipped {_count_phrase(skipped, 'job')} with no extracted skills.")
    if removed and not dry_run:
        if build.clusters:
            lines.append(f"Replaced {_count_phrase(removed, 'previous cluster')}.")
        else:
            lines.append(f"Removed {_count_phrase(removed, 'stored cluster')}.")
    if dry_run:
        lines.append("Dry run: nothing was written.")
    return "\n".join(lines)


def sync_clusters(conn, build: ClusterBuild) -> int:
    """Replace stored clusters with ``build``. Returns how many cluster rows were removed."""
    conn.execute(DELETE_ASSIGNMENTS_SQL)
    deleted = conn.execute(DELETE_CLUSTERS_SQL)
    removed = deleted.rowcount
    if removed is None or removed < 0:
        removed = 0
    run_at = datetime.now(UTC)
    for cluster in build.clusters:
        cluster_id = conn.execute(
            INSERT_CLUSTER_SQL,
            {
                "label": cluster.label,
                "top_skills": pg_text_array(list(cluster.top_skills)),
                "size": cluster.size,
                "run_at": run_at,
            },
        ).scalar_one()
        for job_id in cluster.job_ids:
            conn.execute(INSERT_ASSIGNMENT_SQL, {"job_id": job_id, "cluster_id": cluster_id})
    return int(removed)


def cluster_roles(*, dry_run: bool = False, k: int = DEFAULT_K) -> dict[str, object]:
    """Cluster current jobs and write both tables unless ``dry_run`` is set."""
    if k < 1:
        raise ValueError("k must be a positive integer")
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(FETCH_CLUSTER_JOBS_SQL).all()
    jobs, skipped = jobs_from_rows(rows)
    build = build_role_clusters(jobs, k=k)
    removed = 0
    if not dry_run:
        with engine.begin() as conn:
            removed = sync_clusters(conn, build)
    report = render_report(build, skipped=skipped, dry_run=dry_run, removed=removed)
    summary: dict[str, object] = {
        "dry_run": dry_run,
        "jobs": build.jobs,
        "skipped": skipped,
        "profiles": build.profiles,
        "k_requested": build.k_requested,
        "k_used": build.k_used,
        "too_few": build.too_few,
        "removed": removed,
        "clusters": [
            {
                "label": cluster.label,
                "top_skills": list(cluster.top_skills),
                "top_titles": list(cluster.top_titles),
                "size": cluster.size,
                "job_ids": list(cluster.job_ids),
            }
            for cluster in build.clusters
        ],
        "report": report,
    }
    logged = {key: summary[key] for key in summary if key not in {"clusters", "report"}}
    log.info("Role clustering done: %s", logged)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Group jobs into role clusters from their extracted skills and titles."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Cluster jobs and print the summary without writing",
    )
    parser.add_argument(
        "--k",
        type=_positive_int,
        default=DEFAULT_K,
        help=f"Number of clusters to fit (default: {DEFAULT_K}). Reduced when fewer distinct jobs exist.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    setup_logging()
    result = cluster_roles(dry_run=args.dry_run, k=args.k)
    print(result["report"])


if __name__ == "__main__":
    main()

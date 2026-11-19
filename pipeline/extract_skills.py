"""Extract skills for jobs that do not have job_skills rows yet.

Seeds the skills table from the taxonomy, then upserts job_skills. Re-running
is safe: skills conflict on name, links conflict on (job_id, skill_id), and a
job that already has any link is left alone. Jobs that match nothing stay
pending so a later run can try again (for example after an API key is set).

    python -m pipeline.extract_skills
    python -m pipeline.extract_skills --limit 50
    python -m pipeline.extract_skills --dry-run
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from sqlalchemy import text

from config import get_settings, setup_logging
from db import get_engine
from extraction.llm import SkillLLM, build_llm
from extraction.skills import Skill, SkillHit, SkillMatcher, load_taxonomy, merge_hits

log = logging.getLogger(__name__)

PENDING_JOBS_SQL = """
SELECT id, title, description
FROM jobs
WHERE NOT EXISTS (
    SELECT 1 FROM job_skills WHERE job_skills.job_id = jobs.id
)
ORDER BY id
"""

# CAST, not ::, so SQLAlchemy does not treat ::text[] as a bind parameter.
SEED_SKILL_SQL = text("""
INSERT INTO skills (name, category, aliases)
VALUES (:name, :category, CAST(:aliases AS text[]))
ON CONFLICT (name) DO UPDATE
SET category = EXCLUDED.category,
    aliases = EXCLUDED.aliases
""")

LINK_SKILL_SQL = text("""
INSERT INTO job_skills (job_id, skill_id, method, confidence)
VALUES (:job_id, :skill_id, :method, :confidence)
ON CONFLICT (job_id, skill_id) DO UPDATE
SET method = EXCLUDED.method,
    confidence = EXCLUDED.confidence
WHERE job_skills.confidence < EXCLUDED.confidence
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
        raise argparse.ArgumentTypeError("--limit must be a positive integer")
    return number


def _fetch_jobs(conn, limit: int | None) -> list[tuple[int, str, str | None]]:
    sql = PENDING_JOBS_SQL
    params: dict[str, int] = {}
    if limit is not None:
        sql = f"{sql}\nLIMIT :limit"
        params["limit"] = limit
    rows = conn.execute(text(sql), params).all()
    return [(row.id, row.title, row.description) for row in rows]


def _seed_skills(conn, skills: tuple[Skill, ...]) -> None:
    for skill in skills:
        conn.execute(
            SEED_SKILL_SQL,
            {
                "name": skill.name,
                "category": skill.category,
                "aliases": pg_text_array(list(skill.aliases)),
            },
        )


def _skill_ids(conn) -> dict[str, int]:
    rows = conn.execute(text("SELECT id, name FROM skills")).all()
    return {row.name: int(row.id) for row in rows}


def _write_links(conn, job_id: int, hits: list[SkillHit], ids: dict[str, int]) -> None:
    for hit in hits:
        skill_id = ids.get(hit.name)
        if skill_id is None:
            log.warning("Skipping unknown skill %s on job %s", hit.name, job_id)
            continue
        conn.execute(
            LINK_SKILL_SQL,
            {
                "job_id": job_id,
                "skill_id": skill_id,
                "method": hit.method,
                "confidence": hit.confidence,
            },
        )


def extract_skills(
    *,
    limit: int | None = None,
    dry_run: bool = False,
    llm: SkillLLM | None = None,
    min_skills: int | None = None,
    taxonomy_path: Path | None = None,
) -> dict[str, object]:
    """Match pending jobs and upsert links. dry_run reads jobs and writes nothing."""
    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")
    if llm is None or min_skills is None:
        settings = get_settings()
        if llm is None:
            llm = build_llm(settings)
        if min_skills is None:
            min_skills = settings.llm_min_skills
    if min_skills < 0:
        raise ValueError("min_skills must be >= 0")
    threshold = min_skills
    taxonomy = load_taxonomy(taxonomy_path)
    matcher = SkillMatcher(taxonomy)
    summary: dict[str, object] = {
        "jobs": 0,
        "empty": 0,
        "skills_in_taxonomy": len(taxonomy),
        "skills_seeded": 0,
        "links": 0,
        "spacy": 0,
        "llm": 0,
        "llm_calls": 0,
        "llm_enabled": bool(llm.enabled),
        "dry_run": dry_run,
    }
    if not llm.enabled:
        log.info("LLM skill fallback is off (set LLM_API_KEY to enable it)")

    def consume(conn, *, write: bool) -> None:
        ids = _skill_ids(conn) if write else {}
        jobs = _fetch_jobs(conn, limit)
        summary["jobs"] = len(jobs)
        for job_id, title, description in jobs:
            spacy_hits = matcher.extract(title, description)
            llm_hits: list[SkillHit] = []
            if len(spacy_hits) < threshold and llm.enabled:
                summary["llm_calls"] = int(summary["llm_calls"]) + 1
                llm_hits = llm.extract(title, description, matcher.allowed)
            merged = merge_hits(spacy_hits, llm_hits)
            if write:
                merged = [hit for hit in merged if hit.name in ids]
            if not merged:
                summary["empty"] = int(summary["empty"]) + 1
                continue
            summary["links"] = int(summary["links"]) + len(merged)
            summary["spacy"] = int(summary["spacy"]) + sum(hit.method == "spacy" for hit in merged)
            summary["llm"] = int(summary["llm"]) + sum(hit.method == "llm" for hit in merged)
            if write:
                _write_links(conn, job_id, merged, ids)

    engine = get_engine()
    if dry_run:
        with engine.connect() as conn:
            consume(conn, write=False)
        log.info("Skill extraction dry run: %s", summary)
        return summary
    with engine.begin() as conn:
        _seed_skills(conn, taxonomy)
        summary["skills_seeded"] = len(taxonomy)
        consume(conn, write=True)
    log.info("Skill extraction done: %s", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract skills for jobs that do not have job_skills rows yet."
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="Process at most this many pending jobs (default: all pending jobs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Match skills and print the summary without writing",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    setup_logging()
    print(
        extract_skills(
            limit=args.limit,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()

"""Export a balanced sample of cleaned, non-duplicate jobs for hand labelling.

Reads the database (DATABASE_URL via config). It does not scrape. A job is
included when ``title_normalized`` is set and ``duplicate_of`` is null, which
is the cleaned posting dedupe kept. The sample is spread across sources as
evenly as the data allows. Each output row has an empty ``gold_skills`` list.

    python scripts/export_eval_sample.py
    python scripts/export_eval_sample.py --limit 100 --seed 0 --output data/eval/labelled_postings.jsonl

The same seed and database return the same postings. Re-running replaces the
output file, including any labels already typed into it.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = "data/eval/labelled_postings.jsonl"
DEFAULT_LIMIT = 100

# title_normalized is written by the scraper and again by pipeline.clean.
# duplicate_of is null on the row dedupe kept.
FETCH_CLEAN_JOBS_SQL = text("""
SELECT id, source, title, description
FROM jobs
WHERE duplicate_of IS NULL
  AND title_normalized IS NOT NULL
  AND btrim(title) <> ''
ORDER BY id
""")


@dataclass(frozen=True)
class JobRow:
    """One cleaned, non-duplicate posting chosen for labelling."""

    id: int
    source: str
    title: str
    description: str | None


@dataclass(frozen=True)
class ExportSummary:
    """How many postings were available, and how many were written per source."""

    output: Path
    requested: int
    written: int
    available: int
    by_source: dict[str, int]


def fetch_jobs(conn) -> list[JobRow]:
    """Return cleaned, non-duplicate jobs. ``conn`` is a SQLAlchemy connection."""
    rows = conn.execute(FETCH_CLEAN_JOBS_SQL).all()
    jobs: list[JobRow] = []
    for row in rows:
        jobs.append(
            JobRow(
                id=int(row.id),
                source=str(row.source or ""),
                title=str(row.title or ""),
                description=None if row.description is None else str(row.description),
            )
        )
    return jobs


def select_balanced(rows: Sequence[JobRow], limit: int, rng: random.Random) -> list[JobRow]:
    """Pick up to ``limit`` rows, spread across sources as evenly as possible.

    Sources are visited in name order, one row at a time, so a large source
    does not fill the sample before a smaller one is used. Rows inside a
    source are shuffled with ``rng``. The result is ordered by id.
    """
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    pools: dict[str, list[JobRow]] = {}
    for row in rows:
        pools.setdefault(row.source, []).append(row)
    for pool in pools.values():
        rng.shuffle(pool)
    chosen: list[JobRow] = []
    while len(chosen) < limit:
        active = sorted(source for source, pool in pools.items() if pool)
        if not active:
            break
        for source in active:
            if len(chosen) >= limit:
                break
            chosen.append(pools[source].pop())
    chosen.sort(key=lambda row: row.id)
    return chosen


def posting_record(job: JobRow) -> dict[str, object]:
    """JSON object for one unlabelled posting."""
    return {
        "id": job.id,
        "source": job.source,
        "title": job.title,
        "description": job.description or "",
        "gold_skills": [],
    }


def write_jsonl(path: Path, jobs: Sequence[JobRow]) -> None:
    """Write one JSON object per line. Parent directories are created."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for job in jobs:
            handle.write(json.dumps(posting_record(job), ensure_ascii=False) + "\n")


def export_sample(
    conn,
    output: Path,
    *,
    limit: int = DEFAULT_LIMIT,
    seed: int = 0,
) -> ExportSummary:
    """Read cleaned non-duplicates, sample them, and write the JSONL file."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    jobs = fetch_jobs(conn)
    chosen = select_balanced(jobs, limit, random.Random(seed))
    write_jsonl(output, chosen)
    counts = Counter(job.source for job in chosen)
    return ExportSummary(
        output=output,
        requested=limit,
        written=len(chosen),
        available=len(jobs),
        by_source=dict(sorted(counts.items())),
    )


def render_export(summary: ExportSummary) -> str:
    """Text the CLI prints after writing the sample."""
    lines = [
        f"Wrote {summary.written} postings to {summary.output} "
        f"(requested {summary.requested}, {summary.available} cleaned non-duplicates available)."
    ]
    if summary.by_source:
        lines.append("By source:")
        for source, count in summary.by_source.items():
            lines.append(f"  {source}: {count}")
    else:
        lines.append("No cleaned non-duplicate jobs were available.")
    return "\n".join(lines)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a balanced sample of cleaned, non-duplicate jobs for skill labelling."
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=DEFAULT_LIMIT,
        help=f"How many postings to write (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed. The same seed and database return the same postings (default: 0)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"JSONL path to write, relative to the repo root (default: {DEFAULT_OUTPUT})",
    )
    return parser


def resolve_output(path: str | Path) -> Path:
    """Resolve a relative output path from the repository root."""
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


def main(argv: list[str] | None = None) -> None:
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from config import setup_logging
    from db import get_engine

    args = build_parser().parse_args(argv)
    setup_logging()
    output = resolve_output(args.output)
    with get_engine().connect() as conn:
        summary = export_sample(conn, output, limit=args.limit, seed=args.seed)
    print(render_export(summary))


if __name__ == "__main__":
    main()

"""Export of the labelling sample. A fake database. No live network calls."""

import json
import os
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from scripts.export_eval_sample import (
    FETCH_CLEAN_JOBS_SQL,
    JobRow,
    build_parser,
    export_sample,
    posting_record,
    render_export,
    select_balanced,
)

ROOT = Path(__file__).resolve().parents[1]


class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return _Result(self.rows)


def _jobs():
    rows = []
    for source, count in (("ikman", 40), ("itpro", 10), ("topjobs", 80), ("xpressjobs", 30)):
        for _ in range(count):
            rows.append(
                _Row(
                    id=len(rows) + 1,
                    source=source,
                    title=f"{source} role {len(rows) + 1}",
                    description="Work with Python.",
                )
            )
    return rows


def test_query_keeps_cleaned_non_duplicates_only():
    sql = str(FETCH_CLEAN_JOBS_SQL)
    folded = " ".join(sql.split())
    assert folded.startswith("SELECT id, source, title, description")
    assert "duplicate_of IS NULL" in folded
    assert "title_normalized IS NOT NULL" in folded
    upper = folded.upper()
    assert "INSERT" not in upper
    assert "UPDATE" not in upper
    assert "DELETE" not in upper


def test_sample_is_balanced_across_sources():
    rows = [JobRow(row.id, row.source, row.title, row.description) for row in _jobs()]
    chosen = select_balanced(rows, 100, random.Random(0))
    assert len(chosen) == 100
    assert len({row.id for row in chosen}) == 100
    assert [row.id for row in chosen] == sorted(row.id for row in chosen)
    assert Counter(row.source for row in chosen) == {
        "ikman": 30,
        "itpro": 10,
        "topjobs": 30,
        "xpressjobs": 30,
    }


def test_equal_sources_split_the_sample():
    rows = []
    next_id = 1
    for source in ("ikman", "itpro", "topjobs", "xpressjobs"):
        for _ in range(50):
            rows.append(JobRow(next_id, source, "Title", "Description"))
            next_id += 1
    chosen = select_balanced(rows, 100, random.Random(0))
    assert Counter(row.source for row in chosen) == {
        "ikman": 25,
        "itpro": 25,
        "topjobs": 25,
        "xpressjobs": 25,
    }


def test_short_pool_returns_every_row_sorted_by_id():
    rows = [
        JobRow(3, "topjobs", "C", "d"),
        JobRow(1, "itpro", "A", "d"),
        JobRow(2, "ikman", "B", None),
    ]
    chosen = select_balanced(rows, 100, random.Random(0))
    assert [row.id for row in chosen] == [1, 2, 3]


def test_seed_is_stable():
    rows = [JobRow(index, "itpro", f"Role {index}", "d") for index in range(1, 31)]
    samples = {tuple(row.id for row in select_balanced(rows, 10, random.Random(seed))) for seed in range(5)}
    again = tuple(row.id for row in select_balanced(rows, 10, random.Random(0)))
    assert again == tuple(row.id for row in select_balanced(rows, 10, random.Random(0)))
    assert len(samples) > 1


def test_limit_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        select_balanced([], 0, random.Random(0))


def test_record_has_an_empty_gold_list():
    record = posting_record(JobRow(7, "ikman", "Analyst", None))
    assert record == {
        "id": 7,
        "source": "ikman",
        "title": "Analyst",
        "description": "",
        "gold_skills": [],
    }


def test_export_writes_a_balanced_jsonl_sample(tmp_path):
    conn = _Conn(_jobs())
    output = tmp_path / "eval" / "labelled_postings.jsonl"
    summary = export_sample(conn, output, limit=100, seed=0)
    assert summary.written == 100
    assert summary.available == 160
    assert summary.requested == 100
    assert summary.by_source["itpro"] == 10
    sql = conn.statements[0][0]
    assert "duplicate_of IS NULL" in sql
    assert conn.statements[0][1] is None
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 100
    rows = [json.loads(line) for line in lines]
    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
    assert all(row["gold_skills"] == [] for row in rows)
    assert all(set(row) == {"id", "source", "title", "description", "gold_skills"} for row in rows)
    assert "itpro: 10" in render_export(summary)
    assert "Wrote 100 postings" in render_export(summary)


def test_cli_help_does_not_open_the_database():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.limit == 100
    assert args.seed == 0
    assert args.output == "data/eval/labelled_postings.jsonl"
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite://"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_eval_sample.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "--limit" in result.stdout
    assert "--seed" in result.stdout
    assert "data/eval/labelled_postings.jsonl" in result.stdout

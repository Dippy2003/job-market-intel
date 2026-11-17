"""Mark duplicate jobs. The row with the smallest id is the one we keep."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

from db import get_engine


@dataclass(frozen=True)
class JobKey:
    id: int
    url: str
    content_hash: str | None
    title_normalized: str | None
    company: str | None
    posted_date: date | None


def duplicate_map(rows: list[JobKey]) -> dict[int, int]:
    """Return duplicate id -> kept id.

    Two rows match when they share a URL, a content hash, or the same
    normalized title, company, and posted date.
    """
    parent = {row.id: row.id for row in rows}

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    def group(keys: dict[object, list[int]]) -> None:
        for ids in keys.values():
            first = ids[0]
            for other in ids[1:]:
                union(first, other)

    by_url: dict[str, list[int]] = {}
    by_hash: dict[str, list[int]] = {}
    by_posting: dict[tuple[str, str, date | None], list[int]] = {}
    for row in rows:
        by_url.setdefault(row.url, []).append(row.id)
        if row.content_hash:
            by_hash.setdefault(row.content_hash, []).append(row.id)
        title = (row.title_normalized or "").strip()
        company = re.sub(r"\s+", " ", (row.company or "").strip().lower())
        if title and company:
            by_posting.setdefault((title, company, row.posted_date), []).append(row.id)
    group(by_url)
    group(by_hash)
    group(by_posting)
    return {item: find(item) for item in parent if find(item) != item}


def dedupe_jobs() -> dict[str, int]:
    """Set duplicate_of, then clear it on rows that are no longer duplicates."""
    with get_engine().begin() as conn:
        rows = [
            JobKey(
                id=row.id,
                url=row.url,
                content_hash=row.content_hash,
                title_normalized=row.title_normalized,
                company=row.company,
                posted_date=row.posted_date,
            )
            for row in conn.execute(
                text("""
                    SELECT id, url, content_hash, title_normalized, company, posted_date
                    FROM jobs
                    ORDER BY id
                """)
            )
        ]
        mapping = duplicate_map(rows)
        conn.execute(text("UPDATE jobs SET duplicate_of = NULL"))
        for duplicate_id, kept_id in mapping.items():
            conn.execute(
                text("UPDATE jobs SET duplicate_of = :kept WHERE id = :duplicate"),
                {"kept": kept_id, "duplicate": duplicate_id},
            )
    return {"jobs": len(rows), "duplicates": len(mapping)}

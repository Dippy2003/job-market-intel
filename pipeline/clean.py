"""Normalize titles and locations. Original columns stay unchanged."""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import text

from db import get_engine
from scrapers.base import normalize_title

_LOCATION_ALIASES = {
    "remote": "Remote",
    "wfh": "Remote",
    "work from home": "Remote",
    "hybrid": "Hybrid",
    "hybrid / remote": "Hybrid",
    "all island": "All Island",
}
_TELECOMMUTE = re.compile(r'"jobLocationType"\s*:\s*"TELECOMMUTE"')


def normalize_location(value: str | None) -> str | None:
    """Turn a raw city string into a stable label. Empty input stays empty."""
    if value is None or not value.strip():
        return None
    collapsed = re.sub(r"\s+", " ", value).strip()
    alias = _LOCATION_ALIASES.get(collapsed.lower())
    if alias:
        return alias
    parts: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,/|]", collapsed):
        part = part.strip()
        if not part:
            continue
        label = _LOCATION_ALIASES.get(part.lower(), part.title())
        if label not in seen:
            seen.add(label)
            parts.append(label)
    return ", ".join(parts) or None


def location_from_page(location: str | None, raw_html_path: str | None) -> str | None:
    """Use the saved page when the ad is remote and has no city."""
    normalized = normalize_location(location)
    if normalized is not None or not raw_html_path:
        return normalized
    path = Path(raw_html_path)
    if not path.is_file():
        return None
    html = path.read_text(encoding="utf-8", errors="ignore")
    if _TELECOMMUTE.search(html):
        return "Remote"
    return None


def clean_jobs() -> dict[str, int]:
    """Rewrite title_normalized and location_normalized for every job."""
    with get_engine().begin() as conn:
        rows = conn.execute(
            text("SELECT id, title, location, raw_html_path FROM jobs ORDER BY id")
        ).all()
        remote_filled = 0
        for row in rows:
            location = location_from_page(row.location, row.raw_html_path)
            if row.location is None and location == "Remote":
                remote_filled += 1
            conn.execute(
                text("""
                    UPDATE jobs
                    SET title_normalized = :title, location_normalized = :location
                    WHERE id = :id
                """),
                {"id": row.id, "title": normalize_title(row.title), "location": location},
            )
    return {"jobs": len(rows), "remote_filled": remote_filled}


if __name__ == "__main__":
    from pipeline.dedupe import dedupe_jobs

    print(clean_jobs())
    print(dedupe_jobs())

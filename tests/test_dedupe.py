"""Duplicate grouping. No database."""
from datetime import date

from pipeline.dedupe import JobKey, duplicate_map


def _job(job_id: int, **kwargs: object) -> JobKey:
    data = {
        "url": f"https://itpro.lk/job/{job_id}/",
        "content_hash": f"hash-{job_id}",
        "title_normalized": "software engineer",
        "company": "Acme",
        "posted_date": date(2026, 11, 17),
    }
    data.update(kwargs)
    return JobKey(id=job_id, **data)  # type: ignore[arg-type]


def test_same_content_hash_keeps_lowest_id():
    rows = [
        _job(4, content_hash="same"),
        _job(2, content_hash="same"),
        _job(9, title_normalized="designer", company="Other"),
    ]
    assert duplicate_map(rows) == {4: 2}


def test_same_title_company_and_date_match_across_hashes():
    rows = [
        _job(1, content_hash="a", company="Acme Ltd"),
        _job(3, content_hash="b", company="  acme ltd "),
    ]
    assert duplicate_map(rows) == {3: 1}


def test_same_title_company_and_date_match_across_sources():
    rows = [
        _job(1, url="https://itpro.lk/job/1/", content_hash="itpro-hash"),
        _job(
            2,
            url="https://www.topjobs.lk/employer/JobAdvertismentServlet?jc=9",
            content_hash="topjobs-hash",
        ),
    ]
    assert duplicate_map(rows) == {2: 1}


def test_different_day_is_not_a_duplicate():
    rows = [
        _job(1, posted_date=date(2026, 11, 1)),
        _job(2, posted_date=date(2026, 11, 2)),
    ]
    assert duplicate_map(rows) == {}

"""The first migration must cover every column the base scraper writes."""
from pathlib import Path

SQL = Path("db/migrations/001_jobs_and_scrape_runs.sql").read_text(encoding="utf-8")


def test_jobs_columns_match_scraper_insert():
    for column in (
        "source",
        "url",
        "title",
        "title_normalized",
        "company",
        "location",
        "salary_min",
        "salary_max",
        "description",
        "posted_date",
        "closing_date",
        "content_hash",
        "raw_html_path",
    ):
        assert column in SQL


def test_scrape_runs_columns_match_base_scraper():
    for column in ("source", "finished_at", "pages", "found", "inserted", "errors", "status"):
        assert column in SQL

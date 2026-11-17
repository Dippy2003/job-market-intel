"""ITPro.lk scraper.

robots.txt allows /jobs and /job, asks for a 10 second crawl delay, and
disallows every URL that contains a query string. Pagination (?p=2) is skipped.
The terms of use allow browsing listings and do not forbid copying public ads.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Iterable

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper

LISTING_URL = "https://itpro.lk/jobs/"


def _first_dict(value: object) -> dict:
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value).date()


def _money(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _salary(base_salary: object) -> tuple[float | None, float | None]:
    if not isinstance(base_salary, dict):
        return None, None
    quant = base_salary.get("value", base_salary)
    if isinstance(quant, list):
        quant = quant[0] if quant else {}
    if not isinstance(quant, dict):
        return None, None
    high = quant.get("maxValue", quant.get("value"))
    return _money(quant.get("minValue")), _money(high)


class ItproScraper(BaseScraper):
    """Collect public ITPro job cards, then the JobPosting block on each ad."""

    source = "itpro"
    base_url = "https://itpro.lk"
    min_delay = 10.0
    max_delay = 12.0

    def listing_urls(self) -> Iterable[str]:
        yield LISTING_URL

    def parse_listing(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        found: list[str] = []
        for link in soup.select("article.job-card a.jcl"):
            href = link.get("href")
            if not href or "?" in href:
                continue
            found.append(href if href.startswith("http") else f"https://itpro.lk{href}")
        return found

    def parse_job(self, html: str, url: str) -> dict | None:
        soup = BeautifulSoup(html, "lxml")
        posting = _job_posting(soup)
        if not posting or not posting.get("title"):
            return None
        organization = _first_dict(posting.get("hiringOrganization"))
        address = _first_dict(_first_dict(posting.get("jobLocation")).get("address"))
        description_html = posting.get("description") or ""
        description = BeautifulSoup(description_html, "lxml").get_text("\n", strip=True)
        salary_min, salary_max = _salary(posting.get("baseSalary"))
        company = (organization.get("name") or "").strip() or None
        location = (address.get("addressLocality") or "").strip() or None
        return {
            "title": str(posting["title"]).strip(),
            "company": company,
            "location": location,
            "description": description or None,
            "posted_date": _as_date(posting.get("datePosted")),
            "closing_date": _as_date(posting.get("validThrough")),
            "salary_min": salary_min,
            "salary_max": salary_max,
        }


def _job_posting(soup: BeautifulSoup) -> dict | None:
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.get_text())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


if __name__ == "__main__":
    ItproScraper(dry_run=True).run(max_jobs=2)

"""topjobs.lk scraper.

Requesting /robots.txt redirects to the homepage. That page publishes no
User-agent, Disallow, or Crawl-delay rules, so public pages are allowed.

The daily crawl reads the Recent 100 Jobs listing and each public ad, and
stops at 100 ads. It does not open category "show all" pages, log in, or
submit apply forms. Wait at least 10 seconds between requests. A longer
crawl-delay, if one is published later, replaces that floor.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date, datetime
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from scrapers.base import USER_AGENT, BaseScraper

LISTING_URLS = ("https://www.topjobs.lk/recentjobs.jsp",)
SITE_ROOT = "https://www.topjobs.lk/"
JOB_PARAMS = ("ac", "ec", "jc")

_WINDOW = re.compile(r"""openSizeWindow\(\s*['"]([^'"]+)['"]""", re.IGNORECASE)
_SESSION = re.compile(r";jsessionid=[^?&#]*", re.IGNORECASE)
_PLACEHOLDER_EN = re.compile(
    r"please refer the full details of the job posting as given by the employer\.?",
    re.IGNORECASE,
)
_PLACEHOLDER_SI = "කරුණාකර සේවායෝජකයා විසින් දෙන ලද රැකියා විස්තරය වෙත යොමුවන්න."
_SALARY_RANGE = re.compile(
    r"(?:Rs\.?|LKR)\s*([0-9][0-9,]*(?:\.\d+)?)\s*(?:-|–|to)\s*(?:Rs\.?|LKR)?\s*([0-9][0-9,]*(?:\.\d+)?)",
    re.IGNORECASE,
)


def delay_bounds(min_delay: float, max_delay: float, crawl_delay: float | None) -> tuple[float, float]:
    """Keep a 10 second floor, and honor a longer robots.txt crawl-delay."""
    low = max(float(min_delay), 10.0)
    if crawl_delay is not None and crawl_delay > low:
        low = float(crawl_delay)
    return low, max(float(max_delay), low)


def canonical_job_url(href: str) -> str | None:
    """Turn a listing link into a stable ad URL, or None when it is not an ad.

    ac, ec, and jc are all required. A jc-only URL redirects to an error page.
    The caller page (pg) and the session id are dropped so the same ad is one row.
    """
    href = _SESSION.sub("", unescape(href.strip()))
    if "JobAdvertismentServlet" not in href:
        return None
    parsed = urlparse(urljoin(SITE_ROOT, href))
    host = parsed.netloc.lower()
    if host not in {"www.topjobs.lk", "topjobs.lk"}:
        return None
    if not parsed.path.lower().rstrip("/").endswith("/employer/jobadvertismentservlet"):
        return None
    found = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=False)}
    if any(not found.get(key) for key in JOB_PARAMS):
        return None
    query = urlencode([(key, found[key]) for key in JOB_PARAMS])
    return urlunparse(("https", "www.topjobs.lk", "/employer/JobAdvertismentServlet", "", query, ""))


def _first_dict(value: object) -> dict:
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def _as_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date()
    except ValueError:
        return None


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


def _salary_from_text(value: str | None) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    match = _SALARY_RANGE.search(value)
    if not match:
        return None, None
    return _money(match.group(1)), _money(match.group(2))


def _locations(value: object) -> str | None:
    items = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        address = _first_dict(item.get("address"))
        locality = str(address.get("addressLocality") or "").strip()
        if locality and locality not in names:
            names.append(locality)
    return ", ".join(names) or None


def _clean_description(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = BeautifulSoup(value, "lxml").get_text("\n", strip=True)
    lines: list[str] = []
    for line in text.splitlines():
        line = _PLACEHOLDER_EN.sub("", line).replace(_PLACEHOLDER_SI, "")
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line.strip("."):
            lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned or None


def _job_posting(soup: BeautifulSoup) -> dict | None:
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.get_text())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


class TopjobsScraper(BaseScraper):
    """Collect the public Recent 100 list, then the fields on each ad."""

    source = "topjobs"
    base_url = "https://www.topjobs.lk"
    min_delay = 10.0
    max_delay = 12.0
    max_job_urls = 100

    def __init__(self, dry_run: bool = False):
        super().__init__(dry_run=dry_run)
        crawl_delay = self.robots.crawl_delay(USER_AGENT)
        self.min_delay, self.max_delay = delay_bounds(self.min_delay, self.max_delay, crawl_delay)

    def listing_urls(self) -> Iterable[str]:
        yield from LISTING_URLS

    def parse_listing(self, html: str, url: str) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for raw in _WINDOW.findall(unescape(html)):
            job_url = canonical_job_url(raw)
            if not job_url or job_url in seen:
                continue
            seen.add(job_url)
            found.append(job_url)
            if len(found) >= self.max_job_urls:
                break
        return found

    def parse_job(self, html: str, url: str) -> dict | None:
        soup = BeautifulSoup(html, "lxml")
        posting = _job_posting(soup) or {}
        organization = _first_dict(posting.get("hiringOrganization"))
        title = str(posting.get("title") or "").strip()
        if not title:
            node = soup.select_one("#position")
            title = node.get_text(strip=True) if node else ""
        if not title:
            return None
        company = str(organization.get("name") or "").strip()
        if not company:
            node = soup.select_one("#employer")
            company = node.get_text(strip=True) if node else ""
        location = _locations(posting.get("jobLocation"))
        if not location:
            node = soup.select_one("#adview-job-location")
            location = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""
        remark = soup.select_one("#remark")
        description = _clean_description(remark.decode_contents() if remark else None)
        if not description:
            description = _clean_description(posting.get("description"))
        posted = _as_date(posting.get("datePosted"))
        closing = _as_date(posting.get("validThrough"))
        if closing is None:
            node = soup.select_one("#endDate")
            closing = _as_date(node.get_text(strip=True) if node else None)
        salary_min, salary_max = _salary(posting.get("baseSalary"))
        if salary_min is None and salary_max is None:
            salary_min, salary_max = _salary_from_text(description)
        return {
            "title": title,
            "company": company or None,
            "location": location or None,
            "description": description,
            "posted_date": posted,
            "closing_date": closing,
            "salary_min": salary_min,
            "salary_max": salary_max,
        }


if __name__ == "__main__":
    TopjobsScraper(dry_run=True).run(max_jobs=2)

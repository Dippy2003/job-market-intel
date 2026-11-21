"""XpressJobs scraper (xpressjobs.lk redirects to xpress.jobs).

robots.txt on xpress.jobs allows every path (``Disallow`` is empty) and
publishes no crawl-delay. The public job pages are a JavaScript shell with
no ads in the HTML, so this scraper reads the same public GET endpoints the
site uses to render the IT category: ``/api/jobs/searchJobs`` and
``/api/jobs/publishedJob``. It does not log in, apply, or call recruiter
endpoints.

The IT category is ``/jobs/it-jobs`` (sector friendly name ``it``, id 30).
One page of 20 ads is fetched. Wait at least 10 seconds between requests.
A longer crawl-delay, if one is published later, replaces that floor.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import date, datetime
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup

from scrapers.base import USER_AGENT, BaseScraper

SITE_ROOT = "https://xpress.jobs"
# Public allSectors payload: friendlyName "it" is IT-SWare / Internet.
IT_SECTOR_ID = "30"
IT_FRIENDLY_NAMES = frozenset({"it", "it-hware"})
PAGE_SIZE = 20
_VIEW_PATH = re.compile(r"^/jobs/view/(\d+)(?:/|$)")
_SALARY_WORDS = frozenset({"any", "-", "negotiable", "n/a", "na"})


def delay_bounds(min_delay: float, max_delay: float, crawl_delay: float | None) -> tuple[float, float]:
    """Keep a 10 second floor, and honor a longer robots.txt crawl-delay."""
    low = max(float(min_delay), 10.0)
    if crawl_delay is not None and crawl_delay > low:
        low = float(crawl_delay)
    return low, max(float(max_delay), low)


def it_search_url() -> str:
    """One public IT-category search page. Query filters stay off."""
    query = urlencode(
        {
            "page": 1,
            "pageSize": PAGE_SIZE,
            "sectors": IT_SECTOR_ID,
            "keyword": "",
            "locations": "",
            "jobTypes": "",
            "careerLevels": "",
            "sortBy": "SortedCreateDate DESC",
            "byCVLess": "false",
            "byWalkIn": "false",
        }
    )
    return f"{SITE_ROOT}/api/jobs/searchJobs?{query}"


def job_slug(title: str, company: str | None) -> str:
    """Match the site's public /jobs/view slug (ASCII, like its JavaScript)."""
    raw = f"{title}-{company}" if company else title
    text = raw.lower().strip()
    text = re.sub(r"[^A-Za-z0-9_\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "job"


def canonical_job_url(job_id: object, title: object, company: object) -> str | None:
    """Public ad URL, or None when the row has no id or title."""
    if isinstance(job_id, bool) or not isinstance(job_id, int | str):
        return None
    try:
        number = int(str(job_id))
    except ValueError:
        return None
    if number <= 0 or not isinstance(title, str) or not title.strip():
        return None
    company_name = company.strip() if isinstance(company, str) else None
    slug = job_slug(title.strip(), company_name or None)
    return f"{SITE_ROOT}/jobs/view/{number}/{slug}"


def detail_api_url(url: str) -> str | None:
    """Map a public ad URL to the read-only publishedJob endpoint."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in {"xpress.jobs", "www.xpress.jobs", "xpressjobs.lk", "www.xpressjobs.lk"}:
        return None
    match = _VIEW_PATH.match(parsed.path)
    if not match:
        return None
    return f"{SITE_ROOT}/api/jobs/publishedJob?jobId={int(match.group(1))}"


def _loads(text: str) -> object | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _as_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _salary_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned.lower() in _SALARY_WORDS:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _html_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = BeautifulSoup(value, "lxml").get_text("\n", strip=True)
    cleaned = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or None


def _location(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip(" ,")
    return text or None


def _in_it_category(payload: dict) -> bool:
    """Keep ads tagged IT. A missing sector list was already filtered by search."""
    sectors = payload.get("sectors")
    if not isinstance(sectors, list) or not sectors:
        return True
    names = {
        str(sector.get("friendlyName") or "").strip().lower()
        for sector in sectors
        if isinstance(sector, dict)
    }
    if not names:
        return True
    return bool(names & IT_FRIENDLY_NAMES)


class XpressjobsScraper(BaseScraper):
    """Collect the public IT category, then each ad's published fields."""

    source = "xpressjobs"
    base_url = SITE_ROOT
    min_delay = 10.0
    max_delay = 12.0
    max_job_urls = PAGE_SIZE

    def __init__(self, dry_run: bool = False):
        super().__init__(dry_run=dry_run)
        crawl_delay = self.robots.crawl_delay(USER_AGENT)
        self.min_delay, self.max_delay = delay_bounds(self.min_delay, self.max_delay, crawl_delay)

    def listing_urls(self) -> Iterable[str]:
        yield it_search_url()

    def fetch(self, url: str) -> str | None:
        """Fetch a public ad through its read API. robots.txt is checked for both URLs."""
        target = detail_api_url(url)
        if target and not self.allowed(url):
            self.log.info("Blocked by robots.txt, skipping %s", url)
            return None
        return super().fetch(target or url)

    def parse_listing(self, html: str, url: str) -> list[str]:
        payload = _loads(html)
        if not isinstance(payload, list):
            self._logger().warning(
                "XpressJobs response was not a job list. The HTML is a JavaScript shell "
                "or the public jobs API changed: %s",
                url,
            )
            return []
        found: list[str] = []
        seen: set[str] = set()
        for row in payload:
            if not isinstance(row, dict):
                continue
            job_url = canonical_job_url(row.get("jobId"), row.get("jobTitle"), row.get("organizationName"))
            if not job_url or job_url in seen:
                continue
            seen.add(job_url)
            found.append(job_url)
            if len(found) >= self.max_job_urls:
                break
        return found

    def parse_job(self, html: str, url: str) -> dict | None:
        payload = _loads(html)
        if not isinstance(payload, dict) or not _in_it_category(payload):
            return None
        item = payload.get("jobItem") if isinstance(payload.get("jobItem"), dict) else {}
        organization = payload.get("organization") if isinstance(payload.get("organization"), dict) else {}
        title = str(payload.get("jobTitle") or item.get("jobTitle") or "").strip()
        if not title:
            return None
        company = str(organization.get("organizationName") or item.get("organizationName") or "").strip()
        salary_min = _salary_number(payload.get("minSalary"))
        salary_max = _salary_number(payload.get("maxSalary"))
        if salary_min is not None and salary_max is None:
            salary_max = salary_min
        return {
            "title": title,
            "company": company or None,
            "location": _location(item.get("locations")),
            "description": _html_text(payload.get("jobInfo")),
            "posted_date": _as_date(payload.get("createdDate")),
            "closing_date": _as_date(item.get("expiryDateOnWebsite")),
            "salary_min": salary_min,
            "salary_max": salary_max,
        }

    def _logger(self) -> logging.Logger:
        return getattr(self, "log", logging.getLogger(self.source))


if __name__ == "__main__":
    XpressjobsScraper(dry_run=True).run(max_jobs=2)

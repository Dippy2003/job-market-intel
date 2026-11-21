"""Ikman.lk scraper for the tech / IT jobs category.

``User-agent: *`` allows ``/en/ads/sri-lanka/it-and-network-industry-jobs`` and
``/en/ad/...`` detail pages. It disallows query-string filters, account pages,
and ad edit/delete/report paths. Those rules use ``*`` wildcards, which
Python's robotparser treats as literal text, so this scraper matches them
itself and skips any disallowed URL.

Only the first server-rendered category page is read (25 ads). Pagination and
filters use query strings that robots.txt disallows, and they are not requested.
Wait at least 10 seconds between requests. A longer crawl-delay for this agent,
if one is published later, replaces that floor.

``Disallow: /`` on CCBot, Baiduspider, Sogou, and BLEXBot does not apply to
this scraper.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import date, datetime
from html import unescape
from urllib import robotparser
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from scrapers.base import USER_AGENT, BaseScraper

SITE_ROOT = "https://ikman.lk/"
LISTING_URL = "https://ikman.lk/en/ads/sri-lanka/it-and-network-industry-jobs"
# Patterns from the User-agent: * group of https://ikman.lk/robots.txt.
# A successful live fetch replaces this list.
DEFAULT_DISALLOWS = (
    "/*utm_source*",
    "/*?*c=*",
    "/*?*account=*",
    "/*?*filters=*",
    "/*?*sort=*",
    "/*?*type=*",
    "/*?*query=*",
    "/*/ad/*/delete*",
    "/*/ad/*/edit*",
    "/*/ad/*/report*",
    "/*/password-reset*",
    "/*/password-update",
    "/*--*",
    "/*/ads-locations*",
    "/*/ads-categories*",
    "/*/ads-filters*",
    "/*/ads-type*",
    "/*/saved-search/*",
    "/134461134/",
    "/*?*email=*",
    "/*?*tree.brand=*",
    "/*?*someParam=*",
    "/*?*phones=*",
    "/*?*gclid=*",
    "/*?*scope=*",
    "/*?*locale=*",
    "/*?*similar=*",
    "/*?*categoryName=*",
    "/*?*categoryType=*",
    "/*?*short=*",
    "/*?*actions=*",
    "/*?*deprecation_warning=*",
    "/*?*switch_locale=*",
    "/*?*shop_required=*",
    "/*?*nearby=*",
    "/*?*login-modal",
    "*/confirm",
    "*/promote",
    "*/payment/transaction",
    "*/promote/voucher",
    "*/select-payment",
)
_AD_PATH = re.compile(r"^/en/ad/[^/]+$")
_DEADLINE = re.compile(r"Application deadline:\s*(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", re.IGNORECASE)
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def delay_bounds(min_delay: float, max_delay: float, crawl_delay: float | None) -> tuple[float, float]:
    """Keep a 10 second floor, and honor a longer robots.txt crawl-delay."""
    low = max(float(min_delay), 10.0)
    if crawl_delay is not None and crawl_delay > low:
        low = float(crawl_delay)
    return low, max(float(max_delay), low)


def star_disallow_patterns(lines: Iterable[str]) -> list[str]:
    """Return Disallow paths from the ``User-agent: *`` group only."""
    groups: list[tuple[list[str], list[str]]] = []
    agents: list[str] = []
    rules: list[str] = []
    seen_rule = False

    def flush() -> None:
        nonlocal agents, rules, seen_rule
        if agents:
            groups.append((agents, rules))
        agents = []
        rules = []
        seen_rule = False

    for raw in lines:
        # A comment-only line is not a record break. robotparser only breaks on a blank line.
        if not raw.strip():
            flush()
            continue
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if seen_rule:
                flush()
            agents.append(value.lower())
        elif key == "disallow" and agents:
            seen_rule = True
            if value:
                rules.append(value)
        elif key in {"allow", "crawl-delay", "request-rate"} and agents:
            seen_rule = True
    flush()
    patterns: list[str] = []
    for group_agents, group_rules in groups:
        if "*" in group_agents:
            patterns.extend(group_rules)
    return patterns


def path_and_query(url: str) -> str:
    """Path plus query, with one round of percent-decoding."""
    parsed = urlparse(url)
    path = unquote(parsed.path or "/")
    if not path.startswith("/"):
        path = "/" + path
    query = unquote(parsed.query)
    if query:
        return f"{path}?{query}"
    return path


def robots_match(pattern: str, target: str) -> bool:
    """Google-style robots match: ``*`` is any text and ``$`` anchors the end."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    expression = "^" + "".join(".*" if char == "*" else re.escape(char) for char in body)
    if anchored:
        expression += "$"
    return re.match(expression, target) is not None


def url_is_disallowed(url: str, patterns: Iterable[str]) -> bool:
    target = path_and_query(url)
    return any(robots_match(pattern, target) for pattern in patterns)


def canonical_ad_url(href: str) -> str | None:
    """Absolute English ad URL, or None when the link is not one ad."""
    href = unescape(href.strip())
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    parsed = urlparse(urljoin(SITE_ROOT, href))
    host = parsed.netloc.lower()
    if host not in {"ikman.lk", "www.ikman.lk"}:
        return None
    path = unquote(parsed.path).rstrip("/") or "/"
    if not _AD_PATH.match(path):
        return None
    return f"https://ikman.lk{path}"


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
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _money(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
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


def _job_posting(soup: BeautifulSoup) -> dict | None:
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.get_text())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


def _item_urls(soup: BeautifulSoup) -> list[str]:
    found: list[str] = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.get_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "ItemList":
            continue
        elements = data.get("itemListElement")
        if not isinstance(elements, list):
            continue
        for item in elements:
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                found.append(item["url"])
    return found


class IkmanScraper(BaseScraper):
    """Collect the public IT category page, then each ad's JobPosting block."""

    source = "ikman"
    base_url = "https://ikman.lk"
    min_delay = 10.0
    max_delay = 12.0
    max_job_urls = 25
    wildcard_disallows: tuple[str, ...] | list[str] = DEFAULT_DISALLOWS

    def __init__(self, dry_run: bool = False):
        super().__init__(dry_run=dry_run)
        crawl_delay = self.robots.crawl_delay(USER_AGENT)
        self.min_delay, self.max_delay = delay_bounds(self.min_delay, self.max_delay, crawl_delay)

    def _load_robots(self) -> robotparser.RobotFileParser:
        rp = robotparser.RobotFileParser()
        robots_url = urljoin(self.base_url, "/robots.txt")
        rp.set_url(robots_url)
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
            if response.status_code in (401, 403):
                rp.disallow_all = True
            elif response.ok:
                lines = response.text.splitlines()
                rp.parse(lines)
                self.wildcard_disallows = star_disallow_patterns(lines)
            elif 400 <= response.status_code < 500:
                rp.allow_all = True
        except requests.RequestException as exc:
            self.log.warning("Could not read robots.txt: %s", exc)
        return rp

    def allowed(self, url: str) -> bool:
        if not super().allowed(url):
            return False
        if url_is_disallowed(url, self.wildcard_disallows):
            return False
        return True

    def listing_urls(self) -> Iterable[str]:
        yield LISTING_URL

    def parse_listing(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        hrefs = _item_urls(soup)
        for link in soup.select("a[href]"):
            href = link.get("href")
            if isinstance(href, str):
                hrefs.append(href)
        found: list[str] = []
        seen: set[str] = set()
        logged: set[str] = set()
        for href in hrefs:
            if not isinstance(href, str) or not href.strip():
                continue
            absolute = urljoin(SITE_ROOT, unescape(href.strip()))
            if url_is_disallowed(absolute, self.wildcard_disallows):
                if absolute not in logged:
                    logged.add(absolute)
                    self._logger().info("Blocked by robots.txt, skipping %s", absolute)
                continue
            job_url = canonical_ad_url(absolute)
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
        address = _first_dict(_first_dict(posting.get("jobLocation")).get("address"))
        title = str(posting.get("title") or "").strip()
        if not title:
            node = soup.select_one("[data-testid='title'] h1") or soup.select_one("h1")
            title = node.get_text(strip=True) if node else ""
        if not title:
            return None
        company = str(organization.get("name") or "").strip()
        if not company:
            shop = soup.select_one("a[href*='/en/shops/']")
            company = shop.get_text(" ", strip=True) if shop else ""
        location = _location(address)
        if not location:
            location = _visible_location(soup)
        description = _clean_text(posting.get("description"))
        posted = _as_date(posting.get("datePosted"))
        closing = _as_date(posting.get("validThrough"))
        if closing is None:
            closing = _deadline(soup)
        salary_min, salary_max = _salary(posting.get("baseSalary"))
        return {
            "title": title,
            "company": company or None,
            "location": location,
            "description": description,
            "posted_date": posted,
            "closing_date": closing,
            "salary_min": salary_min,
            "salary_max": salary_max,
        }

    def _logger(self) -> logging.Logger:
        return getattr(self, "log", logging.getLogger(self.source))


def _location(address: dict) -> str | None:
    locality = str(address.get("addressLocality") or "").strip()
    region = str(address.get("addressRegion") or "").strip()
    parts: list[str] = []
    for part in (locality, region):
        if part and part not in parts:
            parts.append(part)
    return ", ".join(parts) or None


def _visible_location(soup: BeautifulSoup) -> str | None:
    parts: list[str] = []
    selectors = (
        "[data-testid='subtitle-sublocation-link']",
        "[data-testid='subtitle-parentlocation-link']",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip(" ,")
        if text and text not in parts:
            parts.append(text)
    return ", ".join(parts) or None


def _deadline(soup: BeautifulSoup) -> date | None:
    match = _DEADLINE.search(soup.get_text(" ", strip=True))
    if not match:
        return None
    month = _MONTHS.get(match.group(2)[:3].lower())
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = BeautifulSoup(value, "lxml").get_text("\n", strip=True)
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return cleaned or None


if __name__ == "__main__":
    IkmanScraper(dry_run=True).run(max_jobs=2)

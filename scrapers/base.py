"""Base scraper: polite fetching, retries, raw HTML archiving, dedup-aware DB inserts.

Subclasses implement:
    source            -> short name, e.g. "topjobs"
    base_url          -> site root, used for robots.txt
    listing_urls()    -> iterable of listing page URLs
    parse_listing()   -> list of job detail URLs from a listing page
    parse_job()       -> dict with keys matching the jobs table
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib import robotparser
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from sqlalchemy import create_engine, text
from urllib3.util.retry import Retry

from config import get_settings

load_dotenv()

USER_AGENT = os.environ.get(
    "SCRAPER_USER_AGENT",
    "job-market-intel/0.1 (student research project; contact: your-email@example.com)",
)
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[\(\[].*?[\)\]]", " ", t)          # drop "(Remote)", "[Urgent]"
    t = re.sub(r"\b(sr|snr)\b\.?", "senior", t)
    t = re.sub(r"\b(jr)\b\.?", "junior", t)
    t = re.sub(r"[^a-z0-9+#.\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def content_hash(title: str, company: str | None, description: str | None) -> str:
    blob = "|".join(re.sub(r"\s+", " ", (x or "")).strip().lower()
                    for x in (title, company, description))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class BaseScraper(ABC):
    source: str = ""
    base_url: str = ""
    min_delay: float = 2.0
    max_delay: float = 4.0
    timeout: int = 20

    def __init__(self, dry_run: bool = False):
        if not self.source or not self.base_url:
            raise ValueError("Subclass must set source and base_url")
        self.log = logging.getLogger(self.source)
        self.dry_run = dry_run
        self.session = self._make_session()
        self.robots = self._load_robots()
        self.engine = None if dry_run else create_engine(get_settings().database_url, pool_pre_ping=True)
        self.stats = {"pages": 0, "found": 0, "inserted": 0, "errors": 0}

    # ---------- HTTP ----------
    def _make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en"})
        retry = Retry(total=3, backoff_factor=2,
                      status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET",), respect_retry_after_header=True)
        s.mount("http://", HTTPAdapter(max_retries=retry))
        s.mount("https://", HTTPAdapter(max_retries=retry))
        return s

    def _load_robots(self) -> robotparser.RobotFileParser:
        rp = robotparser.RobotFileParser()
        robots_url = urljoin(self.base_url, "/robots.txt")
        rp.set_url(robots_url)
        try:
            # Use our own user agent. urllib's default agent gets 403 here, and
            # RobotFileParser then treats the whole site as disallowed.
            response = self.session.get(robots_url, timeout=self.timeout)
            if response.status_code in (401, 403):
                rp.disallow_all = True
            elif response.ok:
                rp.parse(response.text.splitlines())
            elif 400 <= response.status_code < 500:
                rp.allow_all = True
        except requests.RequestException as e:
            self.log.warning("Could not read robots.txt: %s", e)
        return rp

    def allowed(self, url: str) -> bool:
        try:
            return self.robots.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def fetch(self, url: str) -> str | None:
        if not self.allowed(url):
            self.log.info("Blocked by robots.txt, skipping %s", url)
            return None
        time.sleep(random.uniform(self.min_delay, self.max_delay))
        try:
            r = self.session.get(url, timeout=self.timeout)
            r.raise_for_status()
            self.stats["pages"] += 1
            return r.text
        except requests.RequestException as e:
            self.stats["errors"] += 1
            self.log.error("Fetch failed %s: %s", url, e)
            return None

    def save_raw(self, url: str, html: str) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        folder = RAW_DIR / self.source / day
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{hashlib.md5(url.encode()).hexdigest()}.html"
        path.write_text(html, encoding="utf-8")
        return str(path.relative_to(RAW_DIR.parent.parent))

    # ---------- subclass hooks ----------
    @abstractmethod
    def listing_urls(self) -> Iterable[str]: ...

    @abstractmethod
    def parse_listing(self, html: str, url: str) -> list[str]: ...

    @abstractmethod
    def parse_job(self, html: str, url: str) -> dict | None: ...

    # ---------- DB ----------
    def url_exists(self, url: str) -> bool:
        if self.dry_run:
            return False
        with self.engine.connect() as c:
            return c.execute(text("SELECT 1 FROM jobs WHERE url = :u"), {"u": url}).first() is not None

    def save_job(self, job: dict) -> bool:
        job.setdefault("source", self.source)
        job["title_normalized"] = normalize_title(job["title"])
        job["content_hash"] = content_hash(job["title"], job.get("company"), job.get("description"))
        for k in ("company", "location", "salary_min", "salary_max", "description",
                  "posted_date", "closing_date", "raw_html_path"):
            job.setdefault(k, None)
        if self.dry_run:
            self.log.info("DRY RUN: %s | %s", job["title"], job.get("company"))
            return True
        sql = text("""
            INSERT INTO jobs (source, url, title, title_normalized, company, location,
                              salary_min, salary_max, description, posted_date, closing_date,
                              content_hash, raw_html_path)
            VALUES (:source, :url, :title, :title_normalized, :company, :location,
                    :salary_min, :salary_max, :description, :posted_date, :closing_date,
                    :content_hash, :raw_html_path)
            ON CONFLICT (url) DO NOTHING
        """)
        with self.engine.begin() as c:
            return c.execute(sql, job).rowcount == 1

    def _log_run(self, run_id: int | None, status: str) -> int | None:
        if self.dry_run:
            return None
        with self.engine.begin() as c:
            if run_id is None:
                return c.execute(text("INSERT INTO scrape_runs (source) VALUES (:s) RETURNING id"),
                                 {"s": self.source}).scalar()
            c.execute(text("""UPDATE scrape_runs SET finished_at = now(), pages=:pages, found=:found,
                              inserted=:inserted, errors=:errors, status=:status WHERE id=:id"""),
                      {**self.stats, "status": status, "id": run_id})
        return run_id

    # ---------- main loop ----------
    def run(self, max_jobs: int | None = None) -> dict:
        run_id = self._log_run(None, "running")
        status = "ok"
        try:
            for list_url in self.listing_urls():
                html = self.fetch(list_url)
                if not html:
                    continue
                job_urls = self.parse_listing(html, list_url)
                self.stats["found"] += len(job_urls)
                for job_url in job_urls:
                    if max_jobs and self.stats["inserted"] >= max_jobs:
                        return self.stats
                    if self.url_exists(job_url):
                        continue
                    job_html = self.fetch(job_url)
                    if not job_html:
                        continue
                    try:
                        job = self.parse_job(job_html, job_url)
                    except Exception as e:
                        self.stats["errors"] += 1
                        self.log.exception("Parse failed %s: %s", job_url, e)
                        continue
                    if not job or not job.get("title"):
                        continue
                    job["url"] = job_url
                    job["raw_html_path"] = self.save_raw(job_url, job_html)
                    if self.save_job(job):
                        self.stats["inserted"] += 1
                        self.log.info("Inserted %s", job["title"])
            if self.stats["found"] == 0:
                status = "zero_results"
                self.log.warning("Zero results: the site layout may have changed")
        except Exception:
            status = "failed"
            raise
        finally:
            self._log_run(run_id, status)
            self.log.info("Done: %s", self.stats)
        return self.stats

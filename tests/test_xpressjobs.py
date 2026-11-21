"""Parser tests for XpressJobs. They use saved responses and do not touch the network."""
import json
import logging
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scrapers.xpressjobs import (
    XpressjobsScraper,
    canonical_job_url,
    delay_bounds,
    detail_api_url,
    it_search_url,
)

LISTING = Path("tests/fixtures/xpressjobs_it_search.json").read_text(encoding="utf-8")
DETAIL = Path("tests/fixtures/xpressjobs_job_detail.json").read_text(encoding="utf-8")
SHELL = Path("tests/fixtures/xpressjobs_shell.html").read_text(encoding="utf-8")
AD_URL = "https://xpress.jobs/jobs/view/355625/risk-and-governance-engineer-innobot-pvt-ltd"


def _scraper() -> XpressjobsScraper:
    return XpressjobsScraper.__new__(XpressjobsScraper)


def test_listing_url_is_one_it_category_page():
    urls = list(_scraper().listing_urls())
    assert urls == [it_search_url()]
    parsed = urlparse(urls[0])
    assert parsed.netloc == "xpress.jobs"
    assert parsed.path == "/api/jobs/searchJobs"
    params = parse_qs(parsed.query, keep_blank_values=True)
    assert params["page"] == ["1"]
    assert params["pageSize"] == ["20"]
    assert params["sectors"] == ["30"]
    assert params["sortBy"] == ["SortedCreateDate DESC"]
    assert params["byCVLess"] == ["false"]


def test_listing_parser_builds_public_ad_urls_and_drops_duplicates():
    urls = _scraper().parse_listing(LISTING, it_search_url())
    assert urls == [
        AD_URL,
        "https://xpress.jobs/jobs/view/355586/it-web-executive-colombo-07-edys-holdings-pvt-ltd",
    ]


def test_listing_parser_stops_at_twenty_ads():
    rows = [
        {"jobId": number, "jobTitle": f"Engineer {number}", "organizationName": "Acme"}
        for number in range(1, 26)
    ]
    urls = _scraper().parse_listing(json.dumps(rows), it_search_url())
    assert XpressjobsScraper.max_job_urls == 20
    assert len(urls) == 20
    assert urls[0].startswith("https://xpress.jobs/jobs/view/1/")
    assert urls[-1].startswith("https://xpress.jobs/jobs/view/20/")


def test_shell_html_is_not_a_job_list(caplog):
    caplog.set_level(logging.WARNING)
    assert "id=\"root\"" in SHELL
    assert _scraper().parse_listing(SHELL, "https://xpress.jobs/jobs/it-jobs") == []
    assert "JavaScript shell" in caplog.text
    assert _scraper().parse_job(SHELL, AD_URL) is None


def test_detail_parser_reads_public_job_fields():
    job = _scraper().parse_job(DETAIL, AD_URL)
    assert job is not None
    assert job["title"] == "Risk and Governance Engineer"
    assert job["company"] == "Innobot (Pvt) Ltd"
    assert job["location"] == "Colombo, Western Province"
    assert job["posted_date"] == date(2026, 11, 20)
    assert job["closing_date"] == date(2026, 12, 4)
    assert "security posture" in job["description"]
    assert job["salary_min"] is None
    assert job["salary_max"] is None


def test_numeric_salary_is_kept_and_other_sectors_are_skipped():
    html = """
    {"jobTitle":"Software Engineer","minSalary":"180000","maxSalary":"240000",
     "jobInfo":"<p>Build services.</p>","createdDate":"2026-11-18T08:00:00",
     "organization":{"organizationName":"Acme"},
     "jobItem":{"locations":"Colombo","expiryDateOnWebsite":"2026-12-18T00:00:00"},
     "sectors":[{"friendlyName":"it"}]}
    """
    job = _scraper().parse_job(html, AD_URL)
    assert job is not None
    assert job["salary_min"] == 180000
    assert job["salary_max"] == 240000
    assert job["description"] == "Build services."
    other = html.replace('"it"', '"sales"')
    assert _scraper().parse_job(other, AD_URL) is None


def test_public_ad_url_maps_to_the_read_api():
    assert detail_api_url(AD_URL) == "https://xpress.jobs/api/jobs/publishedJob?jobId=355625"
    assert detail_api_url("https://www.xpressjobs.lk/jobs/view/9/role") == (
        "https://xpress.jobs/api/jobs/publishedJob?jobId=9"
    )
    assert detail_api_url(it_search_url()) is None
    assert canonical_job_url(None, "Role", "Acme") is None
    assert canonical_job_url("nope", "Role", "Acme") is None


def test_xpressjobs_waits_at_least_ten_seconds():
    assert XpressjobsScraper.min_delay >= 10
    assert delay_bounds(10, 12, None) == (10, 12)
    assert delay_bounds(10, 12, 5) == (10, 12)
    assert delay_bounds(10, 12, 20) == (20, 20)

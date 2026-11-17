"""Parser tests for ITPro. They use saved HTML and do not touch the network."""
from datetime import date
from pathlib import Path

from scrapers.itpro import ItproScraper

LISTING = Path("tests/fixtures/itpro_jobs_list.html").read_text(encoding="utf-8")
DETAIL = Path("tests/fixtures/itpro_job_detail.html").read_text(encoding="utf-8")


def _scraper() -> ItproScraper:
    return ItproScraper.__new__(ItproScraper)


def test_listing_parser_reads_fifty_job_links():
    urls = _scraper().parse_listing(LISTING, "https://itpro.lk/jobs/")
    assert len(urls) == 50
    assert urls[0] == "https://itpro.lk/job/15802/security-tech-lead-at-orysys-limited/"
    assert all("?" not in url for url in urls)


def test_detail_parser_reads_public_job_fields():
    job = _scraper().parse_job(DETAIL, urls_first())
    assert job is not None
    assert job["title"] == "Security Tech Lead"
    assert job["company"] == "Orysys Limited"
    assert job["location"] == "Colombo"
    assert job["posted_date"] == date(2026, 11, 17)
    assert job["closing_date"] == date(2027, 2, 15)
    assert "secure architecture" in job["description"]
    assert job["salary_min"] is None


def test_detail_parser_accepts_location_list():
    html = """
    <script type="application/ld+json">
    {"@type":"JobPosting","title":"Junior Web Developer",
     "hiringOrganization":[{"@type":"Organization","name":"Prime One"}],
     "jobLocation":[{"@type":"Place","address":[{"addressLocality":"Colombo"},{"addressLocality":"Jaffna"}]}],
     "description":"<p>Build sites.</p>","datePosted":"2026-11-16"}
    </script>
    """
    job = _scraper().parse_job(html, "https://itpro.lk/job/1/x/")
    assert job is not None
    assert job["title"] == "Junior Web Developer"
    assert job["company"] == "Prime One"
    assert job["location"] == "Colombo"
    assert job["posted_date"] == date(2026, 11, 16)


def test_itpro_waits_at_least_ten_seconds():
    assert ItproScraper.min_delay >= 10


def urls_first() -> str:
    return "https://itpro.lk/job/15802/security-tech-lead-at-orysys-limited/"

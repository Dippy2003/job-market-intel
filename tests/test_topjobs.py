"""Parser tests for topjobs.lk. They use saved HTML and do not touch the network."""
from datetime import date
from pathlib import Path

from scrapers.topjobs import TopjobsScraper, canonical_job_url, delay_bounds

LISTING = Path("tests/fixtures/topjobs_recent.html").read_text(encoding="utf-8")
DETAIL = Path("tests/fixtures/topjobs_job_detail.html").read_text(encoding="utf-8")
AD_URL = (
    "https://www.topjobs.lk/employer/JobAdvertismentServlet"
    "?ac=DEFZZZ&ec=DEFZZZ&jc=0001573395"
)


def _scraper() -> TopjobsScraper:
    return TopjobsScraper.__new__(TopjobsScraper)


def test_listing_urls_are_the_recent_page_only():
    urls = list(_scraper().listing_urls())
    assert urls == ["https://www.topjobs.lk/recentjobs.jsp"]
    assert all("vacancybyfunctionalarea" not in url for url in urls)


def test_listing_parser_canonicalizes_public_ads():
    urls = _scraper().parse_listing(LISTING, "https://www.topjobs.lk/recentjobs.jsp")
    assert urls == [
        AD_URL,
        "https://www.topjobs.lk/employer/JobAdvertismentServlet"
        "?ac=0000000240&ec=0000000293&jc=0001573407",
    ]


def test_incomplete_and_non_ad_links_are_dropped():
    assert canonical_job_url("employer/JobAdvertismentServlet?jc=0001573395") is None
    assert canonical_job_url("/TandC.htm") is None
    assert "jsessionid" not in AD_URL
    assert "pg=" not in AD_URL


def test_listing_parser_stops_at_the_page_cap():
    links = []
    for number in range(1, 120):
        links.append(
            "<a href=\"JavaScript:openSizeWindow("
            f"'employer/JobAdvertismentServlet?ac=DEFZZZ&ec=DEFZZZ&jc={number:010d}'"
            ",1098,631,'tjadv')\">Role</a>"
        )
    urls = _scraper().parse_listing("\n".join(links), "https://www.topjobs.lk/recentjobs.jsp")
    assert TopjobsScraper.max_job_urls == 100
    assert len(urls) == 100
    assert urls[0].endswith("jc=0000000001")
    assert urls[-1].endswith("jc=0000000100")


def test_detail_parser_reads_public_job_fields():
    job = _scraper().parse_job(DETAIL, AD_URL)
    assert job is not None
    assert job["title"] == "Android Tech Lead"
    assert job["company"] == "Fortunaglobal (Pvt) Limited"
    assert job["location"] == "Colombo 3, Kandy"
    assert job["posted_date"] == date(2026, 11, 19)
    assert job["closing_date"] == date(2026, 12, 3)
    assert "Kotlin" in job["description"]
    assert "Please refer the full details" not in job["description"]
    assert job["salary_min"] == 250000
    assert job["salary_max"] == 400000


def test_image_only_ad_keeps_structured_fields_and_skips_the_placeholder():
    html = """
    <script type="application/ld+json">
    {"@type":"JobPosting","title":"Receptionist cum HR Assistant",
     "description":"Please refer the full details of the job posting as given by the employer.",
     "datePosted":"2026-11-18","validThrough":"2026-12-18",
     "hiringOrganization":{"name":"Salon Boss (Pvt) Ltd"},
     "jobLocation":{"@type":"Place","address":{"addressLocality":"Nugegoda"}}}
    </script>
    <div id="remark"><p><img alt="" src="/logo/DEFZZZ/ad.jpg"></p></div>
    """
    job = _scraper().parse_job(html, AD_URL)
    assert job is not None
    assert job["title"] == "Receptionist cum HR Assistant"
    assert job["company"] == "Salon Boss (Pvt) Ltd"
    assert job["location"] == "Nugegoda"
    assert job["description"] is None
    assert job["salary_min"] is None
    assert job["posted_date"] == date(2026, 11, 18)
    assert job["closing_date"] == date(2026, 12, 18)


def test_detail_parser_falls_back_to_visible_fields():
    html = """
    <h5 id="employer">Access Engineering PLC</h5>
    <label id="adview-job-location">Colombo 2, Sri Lanka</label>
    <span id="endDate">15/01/2027</span>
    <h3 id="position">Junior Executive - Commercial</h3>
    <div id="remark"><p>Prepare invoices and follow up with clients.</p></div>
    """
    job = _scraper().parse_job(html, AD_URL)
    assert job is not None
    assert job["title"] == "Junior Executive - Commercial"
    assert job["company"] == "Access Engineering PLC"
    assert job["location"] == "Colombo 2, Sri Lanka"
    assert job["posted_date"] is None
    assert job["closing_date"] == date(2027, 1, 15)
    assert "invoices" in job["description"]


def test_structured_salary_is_kept():
    html = """
    <script type="application/ld+json">
    {"@type":"JobPosting","title":"Software Engineer",
     "hiringOrganization":{"name":"Acme"},
     "baseSalary":{"@type":"MonetaryAmount","currency":"LKR",
       "value":{"@type":"QuantitativeValue","minValue":180000,"maxValue":240000}},
     "description":"<p>Build services. Salary: Rs. 1 - 2.</p>"}
    </script>
    """
    job = _scraper().parse_job(html, AD_URL)
    assert job is not None
    assert job["salary_min"] == 180000
    assert job["salary_max"] == 240000


def test_empty_page_is_skipped():
    assert _scraper().parse_job("<html></html>", AD_URL) is None


def test_topjobs_waits_at_least_ten_seconds():
    assert TopjobsScraper.min_delay >= 10
    assert delay_bounds(10, 12, None) == (10, 12)
    assert delay_bounds(10, 12, 5) == (10, 12)
    assert delay_bounds(10, 12, 20) == (20, 20)

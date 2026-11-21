"""Parser tests for Ikman IT jobs. They use saved HTML and do not touch the network."""
import logging
from datetime import date
from pathlib import Path

from scrapers.ikman import (
    DEFAULT_DISALLOWS,
    LISTING_URL,
    IkmanScraper,
    canonical_ad_url,
    delay_bounds,
    path_and_query,
    robots_match,
    star_disallow_patterns,
    url_is_disallowed,
)

LISTING = Path("tests/fixtures/ikman_it_listing.html").read_text(encoding="utf-8")
DETAIL = Path("tests/fixtures/ikman_job_detail.html").read_text(encoding="utf-8")
ROBOTS = Path("tests/fixtures/ikman_robots.txt").read_text(encoding="utf-8")
AD_URL = "https://ikman.lk/en/ad/it-executive-colombo-178"


def _scraper() -> IkmanScraper:
    return IkmanScraper.__new__(IkmanScraper)


def test_listing_url_is_the_it_category_without_a_query():
    urls = list(_scraper().listing_urls())
    assert urls == [LISTING_URL]
    assert "it-and-network-industry-jobs" in urls[0]
    assert "?" not in urls[0]
    assert not url_is_disallowed(urls[0], DEFAULT_DISALLOWS)


def test_star_rules_ignore_other_bots_and_block_wildcards():
    patterns = star_disallow_patterns(ROBOTS.splitlines())
    assert patterns == list(DEFAULT_DISALLOWS)
    category = LISTING_URL
    assert not url_is_disallowed(category, patterns)
    assert not url_is_disallowed(AD_URL, patterns)
    assert url_is_disallowed(category + "?sort=date_desc", patterns)
    assert url_is_disallowed(category + "?filters=it", patterns)
    assert url_is_disallowed("https://ikman.lk/en/ad/some-role/edit", patterns)
    assert url_is_disallowed("https://ikman.lk/en/ad/some-role%2Fedit", patterns)
    assert url_is_disallowed("https://ikman.lk/en/jobs?login-modal=true", patterns)
    assert url_is_disallowed("https://ikman.lk/en/ad/foo/promote", patterns)
    assert not robots_match("/*?*sort=*", path_and_query(AD_URL))


def test_listing_parser_keeps_it_ads_and_logs_disallowed_links(caplog):
    caplog.set_level(logging.INFO)
    urls = _scraper().parse_listing(LISTING, LISTING_URL)
    assert urls == [
        AD_URL,
        "https://ikman.lk/en/ad/it-support-specialist-galle-city-galle",
        "https://ikman.lk/en/ad/computer-hardware-technician-gampaha-263",
    ]
    assert "Blocked by robots.txt, skipping" in caplog.text
    assert "/edit" in caplog.text
    assert "login-modal" in caplog.text
    assert "sort=date_desc" in caplog.text


def test_listing_parser_stops_at_twenty_five_ads():
    items = ",".join(
        f'{{"@type":"ListItem","position":{number},"url":"https://ikman.lk/en/ad/role-{number}"}}'
        for number in range(1, 31)
    )
    html = (
        '<script type="application/ld+json">'
        '{"@type":"ItemList","itemListElement":[' + items + "]}</script>"
    )
    urls = _scraper().parse_listing(html, LISTING_URL)
    assert IkmanScraper.max_job_urls == 25
    assert len(urls) == 25
    assert urls[0].endswith("/role-1")
    assert urls[-1].endswith("/role-25")


def test_detail_parser_reads_public_job_fields():
    job = _scraper().parse_job(DETAIL, AD_URL)
    assert job is not None
    assert job["title"] == "IT executive"
    assert job["company"] == "Sky Tech Solutions PVT LTD"
    assert job["location"] == "Colombo 3, Colombo"
    assert job["posted_date"] == date(2026, 11, 21)
    assert job["closing_date"] == date(2026, 12, 1)
    assert "IT infrastructure" in job["description"]
    assert job["salary_min"] == 100000
    assert job["salary_max"] == 120000


def test_detail_parser_falls_back_to_visible_fields():
    html = """
    <div data-testid="title"><h1>Network Engineer</h1></div>
    <a href="/en/shops/acme-lanka">Acme Lanka</a>
    <a data-testid="subtitle-sublocation-link" href="/en/ads/kandy/it-and-network-industry-jobs">
      <span>Kandy</span>
    </a>
    <div>Application deadline: 15 Jan 2027</div>
    """
    job = _scraper().parse_job(html, "https://ikman.lk/en/ad/network-engineer-kandy")
    assert job is not None
    assert job["title"] == "Network Engineer"
    assert job["company"] == "Acme Lanka"
    assert job["location"] == "Kandy"
    assert job["posted_date"] is None
    assert job["closing_date"] == date(2027, 1, 15)
    assert job["salary_min"] is None
    assert job["description"] is None


def test_non_ad_links_are_dropped():
    assert canonical_ad_url("/en/ads/sri-lanka/jobs") is None
    assert canonical_ad_url("/en/ad/some-role/edit") is None
    assert canonical_ad_url("https://example.com/en/ad/role") is None
    assert _scraper().parse_job("<html></html>", AD_URL) is None


def test_ikman_waits_at_least_ten_seconds():
    assert IkmanScraper.min_delay >= 10
    assert delay_bounds(10, 12, None) == (10, 12)
    assert delay_bounds(10, 12, 20) == (20, 20)

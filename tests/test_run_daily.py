"""Daily pipeline orchestration. Scrapers are mocked."""
import pytest

from pipeline.run_daily import build_parser, run_daily


@pytest.fixture
def daily(monkeypatch):
    """Replace the database steps and both scrapers. Nothing here touches the network."""
    calls = {"itpro": 0, "topjobs": 0, "xpressjobs": 0, "ikman": 0}
    order: list[str] = []

    class _Scraper:
        def __init__(self, name, stats):
            self.name = name
            self.stats = stats

        def __call__(self, dry_run=False):
            calls[self.name] += 1
            order.append(self.name)
            self.dry_run = dry_run
            return self

        def run(self, max_jobs=None):
            self.max_jobs = max_jobs
            return self.stats

    itpro = _Scraper("itpro", {"pages": 1, "found": 10, "inserted": 5, "errors": 0})
    topjobs = _Scraper("topjobs", {"pages": 1, "found": 4, "inserted": 2, "errors": 0})
    xpressjobs = _Scraper("xpressjobs", {"pages": 1, "found": 6, "inserted": 3, "errors": 0})
    ikman = _Scraper("ikman", {"pages": 1, "found": 8, "inserted": 4, "errors": 0})
    monkeypatch.setattr("pipeline.run_daily.setup_logging", lambda: None)
    monkeypatch.setattr("pipeline.run_daily.ItproScraper", itpro)
    monkeypatch.setattr("pipeline.run_daily.TopjobsScraper", topjobs)
    monkeypatch.setattr("pipeline.run_daily.XpressjobsScraper", xpressjobs)
    monkeypatch.setattr("pipeline.run_daily.IkmanScraper", ikman)
    monkeypatch.setattr("pipeline.run_daily.clean_jobs", lambda: {"jobs": 200, "remote_filled": 0})
    monkeypatch.setattr("pipeline.run_daily.dedupe_jobs", lambda: {"jobs": 200, "duplicates": 0})
    counts = iter([200, 205])
    monkeypatch.setattr("pipeline.run_daily.job_count", lambda: next(counts))
    return {
        "itpro": itpro,
        "topjobs": topjobs,
        "xpressjobs": xpressjobs,
        "ikman": ikman,
        "calls": calls,
        "order": order,
    }


def test_run_daily_scrapes_every_source_then_cleans(daily):
    result = run_daily(max_jobs=10)

    assert daily["order"] == ["itpro", "topjobs", "xpressjobs", "ikman"]
    assert daily["calls"] == {"itpro": 1, "topjobs": 1, "xpressjobs": 1, "ikman": 1}
    assert daily["itpro"].dry_run is False
    assert daily["topjobs"].dry_run is False
    assert daily["xpressjobs"].max_jobs == 10
    assert daily["ikman"].max_jobs == 10
    assert daily["itpro"].max_jobs == 10
    assert daily["topjobs"].max_jobs == 10
    assert result["source"] == "all"
    assert result["scrape"]["itpro"]["inserted"] == 5
    assert result["scrape"]["topjobs"]["inserted"] == 2
    assert result["scrape"]["xpressjobs"]["inserted"] == 3
    assert result["scrape"]["ikman"]["inserted"] == 4
    assert result["jobs_before"] == 200
    assert result["jobs_after"] == 205
    assert result["inserted_this_run"] == 5
    assert result["clean"]["jobs"] == 200
    assert result["dedupe"]["duplicates"] == 0


def test_run_daily_one_source(daily):
    result = run_daily(source="topjobs", dry_run=True, max_jobs=5)
    assert daily["calls"] == {"itpro": 0, "topjobs": 1, "xpressjobs": 0, "ikman": 0}
    assert daily["topjobs"].dry_run is True
    assert daily["topjobs"].max_jobs == 5
    assert list(result["scrape"]) == ["topjobs"]


def test_run_daily_skip_scrape(monkeypatch):
    monkeypatch.setattr("pipeline.run_daily.setup_logging", lambda: None)
    monkeypatch.setattr("pipeline.run_daily.clean_jobs", lambda: {"jobs": 200})
    monkeypatch.setattr("pipeline.run_daily.dedupe_jobs", lambda: {"duplicates": 0})
    monkeypatch.setattr("pipeline.run_daily.job_count", lambda: 200)
    result = run_daily(skip_scrape=True)
    assert result["scrape"] == {"skipped": True}
    assert result["clean"]["jobs"] == 200
    assert result["dedupe"]["duplicates"] == 0


def test_run_daily_rejects_unknown_source():
    with pytest.raises(ValueError, match="topjobs"):
        run_daily(source="elsewhere")


def test_cli_keeps_existing_flags_and_defaults_to_all():
    parser = build_parser()
    defaults = parser.parse_args([])
    assert defaults.source == "all"
    assert defaults.max_jobs is None
    assert defaults.skip_scrape is False
    assert defaults.dry_run is False

    selected = parser.parse_args(
        ["--source", "topjobs", "--max-jobs", "5", "--skip-scrape", "--dry-run"]
    )
    assert selected.source == "topjobs"
    assert selected.max_jobs == 5
    assert selected.skip_scrape is True
    assert selected.dry_run is True


def test_cli_accepts_each_source():
    parser = build_parser()
    assert parser.parse_args(["--source", "xpressjobs"]).source == "xpressjobs"
    assert parser.parse_args(["--source", "ikman"]).source == "ikman"


def test_cli_rejects_unknown_source():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--source", "elsewhere"])

"""Daily pipeline orchestration. Scraper is mocked."""
from unittest.mock import patch

from pipeline.run_daily import run_daily


@patch("pipeline.run_daily.dedupe_jobs", return_value={"jobs": 200, "duplicates": 0})
@patch("pipeline.run_daily.clean_jobs", return_value={"jobs": 200, "remote_filled": 0})
@patch("pipeline.run_daily.job_count", side_effect=[200, 205])
@patch("pipeline.run_daily.ItproScraper")
def test_run_daily_scrape_then_clean(mock_scraper, mock_count, mock_clean, mock_dedupe):
    mock_scraper.return_value.run.return_value = {
        "pages": 1,
        "found": 10,
        "inserted": 5,
        "errors": 0,
    }
    result = run_daily(max_jobs=10)

    mock_scraper.assert_called_once_with(dry_run=False)
    mock_scraper.return_value.run.assert_called_once_with(max_jobs=10)
    mock_clean.assert_called_once()
    mock_dedupe.assert_called_once()
    assert result["jobs_before"] == 200
    assert result["jobs_after"] == 205
    assert result["inserted_this_run"] == 5


@patch("pipeline.run_daily.dedupe_jobs", return_value={"duplicates": 0})
@patch("pipeline.run_daily.clean_jobs", return_value={"jobs": 200})
@patch("pipeline.run_daily.job_count", return_value=200)
def test_run_daily_skip_scrape(mock_count, mock_clean, mock_dedupe):
    result = run_daily(skip_scrape=True)
    assert result["scrape"] == {"skipped": True}
    mock_clean.assert_called_once()
    mock_dedupe.assert_called_once()
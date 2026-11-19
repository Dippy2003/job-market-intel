# Job Market Intelligence Platform (Sri Lanka)
Scrapes Sri Lankan job postings, extracts in-demand skills, tracks and forecasts demand, with a CV skill-gap checker.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # then fill in DATABASE_URL
python -m db            # should log "Connected: PostgreSQL ..."
alembic upgrade head    # stamp 0001 first if jobs and scrape_runs already exist
pytest && ruff check .
python -m pipeline.run_daily                          # scrape ITPro and topjobs.lk, then clean + dedupe
python -m pipeline.run_daily --source itpro           # ITPro only
python -m pipeline.run_daily --source topjobs         # topjobs.lk Recent 100 only
python -m pipeline.run_daily --source topjobs --max-jobs 5 --dry-run
python -m pipeline.run_daily --skip-scrape            # clean + dedupe only
```

topjobs.lk does not publish a robots.txt (`/robots.txt` redirects to the homepage, which has no Disallow or Crawl-delay). The scraper waits at least 10 seconds between requests and only reads the public Recent 100 Jobs page plus each ad. It does not log in, open apply forms, or walk category "show all" pages. The same job on ITPro and topjobs is marked by the existing dedupe when the normalized title, company, and posted date match.

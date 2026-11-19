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
python -m pipeline.run_daily              # scrape ITPro, then clean + dedupe
python -m pipeline.run_daily --skip-scrape  # clean + dedupe only
```

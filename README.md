<div align="center">

# 🇱🇰 Job Market Intelligence Platform (Sri Lanka)

**Scrape Sri Lankan tech job ads, pull out the skills employers ask for, and forecast which ones are heading up.**

![Python 3.11](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/database-Neon%20Postgres-4169E1?logo=postgresql&logoColor=white)
![spaCy](https://img.shields.io/badge/NLP-spaCy-09A3D5?logo=spacy&logoColor=white)
![Prophet](https://img.shields.io/badge/forecasting-Prophet-0B6EFD)
![Lint](https://img.shields.io/badge/lint-ruff-D7FF64)
![Status](https://img.shields.io/badge/status-in%20development-orange)

</div>

---

## ✨ What it does

Every run collects public job ads from **ITPro.lk** and **topjobs.lk**, cleans and de-duplicates them, finds the skills mentioned in each ad, and turns those into **weekly demand numbers** and an **8-week forecast** per skill. The goal is to answer questions like *"Is demand for Docker growing in Sri Lanka?"* with data instead of guesses.

## 🧭 How it works

```mermaid
flowchart LR
    A[ITPro.lk] --> S[Scrapers<br/>polite, robots.txt aware]
    B[topjobs.lk<br/>Recent 100] --> S
    S --> C[Clean + dedupe<br/>titles, locations, duplicates]
    C --> D[(Neon Postgres<br/>jobs)]
    D --> E[Skill extraction<br/>spaCy PhraseMatcher]
    G[Gemini fallback<br/>optional] -.-> E
    E --> F[(skills + job_skills)]
    F --> H[Weekly trends<br/>count and share per skill]
    H --> I{8+ weeks<br/>of data?}
    I -- yes --> J[Prophet forecast]
    I -- "2 to 7 weeks" --> K[Linear fallback forecast]
    J --> L[(skill_trends + forecasts)]
    K --> L
```

## 🚀 Features and status

| Feature | Status | Notes |
| --- | --- | --- |
| ITPro.lk scraper | ✅ Done | Category pages, 10 s crawl delay, raw HTML archived under `data/raw/` |
| topjobs.lk scraper | ✅ Done | Public "Recent 100 Jobs" page, 10 s+ delay, up to 100 ads per run |
| Cleaning and de-duplication | ✅ Done | Normalized titles and locations; the same job on two sites is flagged via `duplicate_of` |
| Database schema + Alembic migrations | ✅ Done | `jobs`, `scrape_runs`, `skills`, `job_skills`, `skill_trends`, `forecasts`, `role_clusters` |
| Skill extraction | ✅ Done | 391-skill taxonomy, spaCy PhraseMatcher, optional Gemini fallback |
| Weekly trends + forecasts | ✅ Done | Prophet, or a linear fallback when there is too little history |
| Role clustering | 🚧 In progress | `role_clusters` table exists; the clustering step is being built |
| REST API, dashboard, CV skill-gap checker | 🗓️ Planned | `api/` and `dashboard/` are placeholders for now |

## 🛠️ Tech stack

- **Language:** Python 3.11
- **Scraping:** `requests`, `BeautifulSoup4`, `lxml`
- **Database:** PostgreSQL on [Neon](https://neon.tech), via SQLAlchemy 2 and `psycopg` 3, with Alembic migrations
- **NLP:** spaCy (`PhraseMatcher` on a blank English pipeline, so no model download is needed), optional Gemini LLM fallback
- **Forecasting:** Prophet, with a least-squares linear fallback
- **Config:** `pydantic-settings` and `python-dotenv`
- **Quality:** `pytest` and `ruff`

## 📁 Project structure

```text
job-market-intel/
├── scrapers/            # base.py (polite fetching, retries, robots.txt), itpro.py, topjobs.py
├── pipeline/            # run_daily.py, clean.py, dedupe.py, extract_skills.py, compute_trends.py
├── extraction/          # skills.py (PhraseMatcher), llm.py (optional Gemini fallback)
├── analytics/           # trends.py (weekly counts), forecast.py (Prophet + linear fallback)
├── db/                  # SQLAlchemy models, Alembic migrations (db/alembic), legacy SQL
├── data/
│   └── skills_taxonomy.json   # 391 skills with categories and aliases
├── api/                 # planned: FastAPI routes
├── dashboard/           # planned
├── tests/               # pytest suite with HTML fixtures
├── config.py            # settings loaded from environment / .env
├── alembic.ini
├── requirements.txt
└── .env.example
```

## ⚙️ Setup

You need Python 3.11 and a PostgreSQL database (a free [Neon](https://neon.tech) project works well).

**Windows (PowerShell)**

```powershell
git clone https://github.com/Dippy2003/job-market-intel.git
cd job-market-intel
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and set DATABASE_URL
python -m db              # should log "Connected: PostgreSQL ..."
alembic upgrade head
```

**macOS / Linux (bash)**

```bash
git clone https://github.com/Dippy2003/job-market-intel.git
cd job-market-intel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set DATABASE_URL
python -m db              # should log "Connected: PostgreSQL ..."
alembic upgrade head
```

> If the `jobs` and `scrape_runs` tables already exist from an earlier setup, run `alembic stamp 0001` before `alembic upgrade head`.

### Configuration (`.env`)

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | yes | Postgres connection string, e.g. `postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require` |
| `LLM_API_KEY` | no | Gemini key. Leave blank to skip the LLM fallback |
| `LLM_MODEL` | no | Defaults to `gemini-1.5-flash` |
| `LLM_MIN_SKILLS` | no | Fallback runs only for ads with fewer matches than this (default `2`) |
| `SCRAPER_USER_AGENT` | no | Identify your scraper and add a contact email |
| `LOG_LEVEL` | no | Defaults to `INFO` |

Never commit your `.env` file.

## ▶️ Usage

```bash
# 1. Scrape, clean and de-duplicate
python -m pipeline.run_daily                              # ITPro + topjobs.lk
python -m pipeline.run_daily --source itpro               # ITPro only
python -m pipeline.run_daily --source topjobs             # topjobs.lk only
python -m pipeline.run_daily --source topjobs --max-jobs 5 --dry-run
python -m pipeline.run_daily --skip-scrape                # clean + dedupe existing rows only

# 2. Extract skills from jobs that have none yet
python -m pipeline.extract_skills
python -m pipeline.extract_skills --limit 50 --dry-run

# 3. Weekly demand + 8-week forecasts
python -m pipeline.compute_trends
python -m pipeline.compute_trends --top 15 --dry-run
```

All commands work the same in PowerShell. `--dry-run` computes and prints without writing to the database, and re-running any step is safe (rows are upserted).

## 🔍 How the analysis works

**Skill extraction.** `data/skills_taxonomy.json` lists each skill with a category and aliases (for example `golang`, `k8s`). A case-insensitive PhraseMatcher finds them in the title and description. Short names are matched as whole tokens only, so `C` does not match inside `C++` and `Go` does not match `Google`. Overlaps keep the longer match (`SQL Server` over `SQL`). If an ad yields fewer than `LLM_MIN_SKILLS` skills and `LLM_API_KEY` is set, Gemini suggests catalog skills at a lower confidence. To add a skill, edit the JSON file.

**Trends.** Weeks start on Monday. Each skill gets a weekly job `count` and a `share` (count divided by all jobs that week). Duplicate postings are excluded.

**Forecasts.** With eight or more weeks of history a skill is forecast with **Prophet** (`prophet-weekly-1`). With two to seven weeks it uses a **linear fallback** (`linear-fallback-1`) with an 80% band. Counts never go below zero, and skills seen in only one week are skipped. This keeps the forecast honest while the dataset is still young.

## ✅ Tests and linting

```bash
pytest -q
ruff check .
```

The test suite runs offline using saved HTML fixtures, and the Prophet fit is mocked.

## 🗺️ Roadmap

- [x] ITPro.lk scraper
- [x] topjobs.lk scraper
- [x] Database schema and Alembic migrations
- [x] Cleaning and de-duplication
- [x] Skill extraction (spaCy + optional Gemini fallback)
- [x] Weekly trends and 8-week forecasts (Prophet + linear fallback)
- [ ] Role clustering *(in progress)*
- [ ] FastAPI REST API
- [ ] Dashboard
- [ ] CI with GitHub Actions
- [ ] More scrapers (XpressJobs, Ikman)
- [ ] Skill-extraction accuracy evaluation against a hand-labelled sample
- [ ] CV skill-gap checker

## 🤝 Ethical scraping

This is a student research project and it tries to be a good citizen:

- It reads each site's `robots.txt` and skips any URL it disallows.
- It waits **at least 10 seconds** between requests on both ITPro.lk and topjobs.lk, and the topjobs.lk scraper honors a longer `Crawl-delay` if one is ever published.
- It only reads public listing and ad pages. It never logs in, submits forms, or applies to jobs.
- It identifies itself with a descriptive `User-Agent`. Set `SCRAPER_USER_AGENT` to include your own contact email.

If you run it, please keep these limits in place.

## 👤 Author

**Amarasie Piyathissa** — Computer Engineering student, University of Ruhuna  
GitHub: [@Dippy2003](https://github.com/Dippy2003)

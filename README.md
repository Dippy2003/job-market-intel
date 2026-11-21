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

Every run collects public job ads from **ITPro.lk** and **topjobs.lk**, cleans and de-duplicates them, finds the skills mentioned in each ad, and turns those into **weekly demand numbers**, an **8-week forecast** per skill, and **role clusters** such as Backend, Frontend, and Data/ML. The goal is to answer questions like *"Is demand for Docker growing in Sri Lanka?"* with data instead of guesses.

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
    F --> M[Role clusters<br/>KMeans on skills]
    H --> I{8+ weeks<br/>of data?}
    I -- yes --> J[Prophet forecast]
    I -- "2 to 7 weeks" --> K[Linear fallback forecast]
    J --> L[(skill_trends + forecasts)]
    K --> L
    M --> N[(role_clusters)]
```

## 🚀 Features and status

| Feature | Status | Notes |
| --- | --- | --- |
| ITPro.lk scraper | ✅ Done | Category pages, 10 s crawl delay, raw HTML archived under `data/raw/` |
| topjobs.lk scraper | ✅ Done | Public "Recent 100 Jobs" page, 10 s+ delay, up to 100 ads per run |
| Cleaning and de-duplication | ✅ Done | Normalized titles and locations; the same job on two sites is flagged via `duplicate_of` |
| Database schema + Alembic migrations | ✅ Done | `jobs`, `scrape_runs`, `skills`, `job_skills`, `skill_trends`, `forecasts`, `role_clusters`, `job_role_clusters` |
| Skill extraction | ✅ Done | 391-skill taxonomy, spaCy PhraseMatcher, optional Gemini fallback |
| Weekly trends + forecasts | ✅ Done | Prophet, or a linear fallback when there is too little history |
| Role clustering | ✅ Done | KMeans on binary skill TF-IDF; labels such as Backend, Frontend, Data/ML |
| REST API | ✅ Done | Read-only FastAPI: jobs, weekly skill demand, 8-week forecasts, role clusters |
| Dashboard | ✅ Done | Streamlit tabs for jobs, skill trends, 8-week forecasts, and role clusters |
| CV skill-gap checker | 🗓️ Planned | Not started |

## 🛠️ Tech stack

- **Language:** Python 3.11
- **Scraping:** `requests`, `BeautifulSoup4`, `lxml`
- **Database:** PostgreSQL on [Neon](https://neon.tech), via SQLAlchemy 2 and `psycopg` 3, with Alembic migrations
- **NLP:** spaCy (`PhraseMatcher` on a blank English pipeline, so no model download is needed), optional Gemini LLM fallback
- **Forecasting:** Prophet, with a least-squares linear fallback
- **Clustering:** scikit-learn KMeans on binary TF-IDF skill vectors
- **API:** FastAPI, served with uvicorn. Interactive docs at `/docs`
- **Dashboard:** Streamlit. It calls the API over HTTP
- **Config:** `pydantic-settings` and `python-dotenv`
- **Quality:** `pytest` and `ruff`

## 📁 Project structure

```text
job-market-intel/
├── scrapers/            # base.py (polite fetching, retries, robots.txt), itpro.py, topjobs.py
├── pipeline/            # run_daily.py, clean.py, dedupe.py, extract_skills.py, compute_trends.py, cluster_roles.py
├── extraction/          # skills.py (PhraseMatcher), llm.py (optional Gemini fallback)
├── analytics/           # trends.py, forecast.py (Prophet + linear fallback), clusters.py
├── db/                  # SQLAlchemy models, Alembic migrations (db/alembic), legacy SQL
├── data/
│   └── skills_taxonomy.json   # 391 skills with categories and aliases
├── api/                 # read-only FastAPI routes (uvicorn api.main:app)
├── dashboard/           # Streamlit app (app.py) and API client (api_client.py)
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
| `CORS_ORIGINS` | no | Comma-separated browser origins for the API. Defaults to `*` |
| `API_BASE_URL` | no | Base URL of the API for the dashboard. Defaults to `http://127.0.0.1:8000` |

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

# 4. Group jobs into role clusters
python -m pipeline.cluster_roles
python -m pipeline.cluster_roles --k 8 --dry-run

# 5. Read-only API (jobs, weekly skill demand, 8-week forecasts, role clusters)
uvicorn api.main:app

# 6. Dashboard (the API must already be running; details below)
streamlit run dashboard/app.py
```

Interactive docs: <http://127.0.0.1:8000/docs>. The app reads `DATABASE_URL` from `.env` through `config.py`. Set `CORS_ORIGINS` when a browser on another origin should call the API.

All commands work the same in PowerShell. `--dry-run` computes and prints without writing to the database. Re-running a step is safe: skills, trends, and forecasts are upserted, and clustering replaces the previous run.

## 📊 Run the dashboard

The Streamlit app in `dashboard/` is a view of the API. Start the API first, from the project root, so it can read `DATABASE_URL` from `.env`:

```bash
uvicorn api.main:app
```

In a second terminal, from the same directory:

```bash
streamlit run dashboard/app.py
```

Open <http://127.0.0.1:8501>. The app calls <http://127.0.0.1:8000> unless `API_BASE_URL` is set in the environment or in `.env`.

The four tabs are:

- **Jobs** filters by source (`itpro`, `topjobs`, or all), a keyword (title, company, location, or description), and an exact skill name.
- **Skill trends** is a line chart of one skill over the newest N weeks.
- **Forecasts** ranks skills by the latest week of their stored 8-week forecast.
- **Roles** lists each cluster with the skills that define it.

Responses are cached for 10 minutes (`st.cache_data(ttl=600)`). When the API is down, the page shows **API not reachable** and tells you to start `uvicorn api.main:app`.

## 🔍 How the analysis works

**Skill extraction.** `data/skills_taxonomy.json` lists each skill with a category and aliases (for example `golang`, `k8s`). A case-insensitive PhraseMatcher finds them in the title and description. Short names are matched as whole tokens only, so `C` does not match inside `C++` and `Go` does not match `Google`. Overlaps keep the longer match (`SQL Server` over `SQL`). If an ad yields fewer than `LLM_MIN_SKILLS` skills and `LLM_API_KEY` is set, Gemini suggests catalog skills at a lower confidence. To add a skill, edit the JSON file.

**Trends.** Weeks start on Monday. Each skill gets a weekly job `count` and a `share` (count divided by all jobs that week). Duplicate postings are excluded.

**Forecasts.** With eight or more weeks of history a skill is forecast with **Prophet** (`prophet-weekly-1`). With two to seven weeks it uses a **linear fallback** (`linear-fallback-1`) with an 80% band. Counts never go below zero, and skills seen in only one week are skipped. This keeps the forecast honest while the dataset is still young.

**Role clusters.** `python -m pipeline.cluster_roles` groups non-duplicate jobs that already have skills. Each job is a binary TF-IDF vector of its skill names plus useful words from the title (seniority and generic words such as "engineer" are left out). KMeans uses `random_state=42`. The default `--k` is 6, and it drops when there are fewer distinct skill profiles. Fewer than 2 jobs with skills is reported and not clustered. Labels come from the skills and titles that dominate a cluster, for example Backend, Frontend, Data/ML, DevOps, QA, or Mobile. Two clusters that would share a name get the top skill appended. The run replaces the previous one: `role_clusters` stores the label, top skills, size, and `run_at`, and `job_role_clusters` stores which job is in which cluster (Alembic `0003`). If the database is already at `0002`, apply the new table with `alembic upgrade head`.

## ✅ Tests and linting

```bash
pytest -q
ruff check .
```

The test suite runs offline using saved HTML and job fixtures. The Prophet fit is mocked, and role clustering does not call the network. API tests use FastAPI's TestClient and an in-memory SQLite database, so they do not call Neon. Dashboard client tests mock `requests` and check the URL, query params, and parsed JSON for each helper.

## 🗺️ Roadmap

- [x] ITPro.lk scraper
- [x] topjobs.lk scraper
- [x] Database schema and Alembic migrations
- [x] Cleaning and de-duplication
- [x] Skill extraction (spaCy + optional Gemini fallback)
- [x] Weekly trends and 8-week forecasts (Prophet + linear fallback)
- [x] Role clustering (KMeans on extracted skills)
- [x] FastAPI REST API
- [x] Dashboard
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

**Dipna Wijesinghe** — Data science Student  
GitHub: [@Dippy2003](https://github.com/Dippy2003)

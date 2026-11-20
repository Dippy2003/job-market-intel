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
python -m pipeline.extract_skills                     # skills for jobs that have none yet
python -m pipeline.extract_skills --limit 50 --dry-run
python -m pipeline.compute_trends                     # weekly skill demand, then an 8-week forecast
python -m pipeline.compute_trends --top 15 --dry-run
```

The same `python -m` commands work in PowerShell. On Windows the venv lives at `.venv\Scripts\activate`.

topjobs.lk does not publish a robots.txt (`/robots.txt` redirects to the homepage, which has no Disallow or Crawl-delay). The scraper waits at least 10 seconds between requests and only reads the public Recent 100 Jobs page plus each ad. It does not log in, open apply forms, or walk category "show all" pages. The same job on ITPro and topjobs is marked by the existing dedupe when the normalized title, company, and posted date match.

## Skill extraction

`python -m pipeline.extract_skills` reads jobs that do not yet have `job_skills` rows, finds skills in the title and description, and upserts `skills` and `job_skills` (Alembic `0002`).

```bash
python -m pipeline.extract_skills
python -m pipeline.extract_skills --limit 50
python -m pipeline.extract_skills --dry-run
```

The catalog is `data/skills_taxonomy.json`: canonical name, category, and aliases (150+ tech skills). Edit that file to add a skill. The matcher is spaCy's PhraseMatcher on `spacy.blank("en")`. It is case-insensitive and does not use lemma tags, so CI does not download `en_core_web_sm`. `spacy` is listed in `requirements.txt` for this step; nothing else was added. Aliases cover plurals and abbreviations (`golang`, `k8s`, `c++17`).

Short names are whole tokens only. `C` does not match inside `C++`, `C#`, or `Objective-C`. `Go` does not match inside `Google` or `main.go`, and it is ignored in phrases such as "go to" and "go-live" unless the token is in a skill list or next to a skill word ("Go developer", "experience with Go"). `R` does not match `R&D`. When two patterns overlap, the longer one is kept (`SQL Server` rather than `SQL`, `React Native` rather than `React`).

Matcher rows use `method = 'spacy'` and confidence `0.9500` (`0.8500` for C, R, and Go). If a job has fewer than `LLM_MIN_SKILLS` matches (default 2) and `LLM_API_KEY` is set, the fallback asks Gemini (`LLM_MODEL`, default `gemini-1.5-flash`) for catalog names and stores them with `method = 'llm'` and confidence `0.6500`. A blank key skips that call. The key is read from `.env` through `config.py` and is not hardcoded. Put a Gemini API key in `LLM_API_KEY` only if you want the fallback.

Re-running is safe. Skills upsert on `name`, links upsert on `(job_id, skill_id)`, and jobs that already have links are skipped. A job that matches nothing is left pending, so a later run can fill it in. `--dry-run` prints the summary and does not write.

## Skill trends and forecasts

`python -m pipeline.compute_trends` rebuilds weekly demand and an 8-week forecast, then prints the top skills for the latest week in the data.

```bash
python -m pipeline.compute_trends
python -m pipeline.compute_trends --top 15
python -m pipeline.compute_trends --dry-run
```

Weeks start on Monday. A job counts on `posted_date`. If that is missing, it counts on the Sri Lanka date of `scraped_at` (UTC+5:30). Rows with `duplicate_of` set are left out. `count` is jobs that list the skill. `share` is that count divided by every job that week, including jobs with no skills. Trend rows upsert on `(skill_id, period_start)`.

Prophet (`prophet` in `requirements.txt`, saved as `prophet-weekly-1`) runs when a skill's span is at least eight weeks. Seasonality stays off: the series is already weekly, and the corpus is only a few weeks (about 200 jobs). Two to seven weeks use a linear fallback (`linear-fallback-1`): least squares on the week index, with an 80% band (20% of the level when only two points exist). Counts are clipped at zero. A skill seen in only one week is skipped. A missing Prophet install or a failed fit uses the same fallback and does not stop the run. The first real Prophet fit compiles a Stan model; later fits reuse it. Forecast rows upsert on `(skill_id, ds, model_version)`. A re-run deletes demand rows and future forecast rows the current jobs no longer support, and leaves older forecast dates in place. `--dry-run` prints the ranking and writes nothing. `--top` only changes how many skills are printed.

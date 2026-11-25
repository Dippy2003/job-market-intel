# Deployment

Host the read-only API and the Next.js app yourself. CI lints and tests on every push to `main`. Deploying is a separate step you run on your host.

Run scrapers, skill extraction, trends, and clustering from a machine you control, with the same `DATABASE_URL` the API uses. Those commands talk to the public job boards and write PostgreSQL. The API process only reads the database. The Next.js app only calls the API.

Set every variable in the host's dashboard. Keep values out of git, Dockerfiles, `vercel.json`, and shell history that you commit. Names are listed at the end. Placeholders live in `.env.example` and `web/.env.example`.

## Database

Create a PostgreSQL database (Neon works). Put its connection string in `DATABASE_URL` for the machine that runs migrations. `config.py` rewrites a `postgresql://` or `postgres://` URL to the `psycopg` driver. `db/alembic/env.py` reads that setting. Leave `alembic.ini` without a real URL.

On a new database:

```bash
alembic upgrade head
```

That applies `0001` (jobs and scrape runs), `0002` (skills, trends, forecasts), and `0003` (role clusters).

`python -m db` checks the connection and applies any pending files in `db/migrations/`. Those files create the early `jobs` tables if Alembic has not. On a new database, run Alembic first. If `python -m db` already created `jobs` and `scrape_runs`, stamp the matching revision and then upgrade:

```bash
alembic stamp 0001
alembic upgrade head
```

Fill the tables from your own machine after the schema exists:

```bash
python -m pipeline.run_daily
python -m pipeline.extract_skills
python -m pipeline.compute_trends
python -m pipeline.cluster_roles
```

Keep the scraper delays and `robots.txt` checks as they are in the scraper classes. The API host does not need to run this batch.

## API

The process is the same one CI installs and the test suite imports:

```bash
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port "$PORT"
```

Python 3.11 matches `.github/workflows/ci.yml`. `--host 0.0.0.0` is what a container or platform router can reach. `PORT` is the port the host sets. Locally, `uvicorn api.main:app` is enough, and it listens on port 8000.

`requirements.txt` includes the batch libraries (spaCy, scikit-learn, Prophet, Streamlit) because scrapers, forecasts, and the API share one file. The API process does not fit Prophet when it serves a request. A host image needs whatever that install needs, including a compiler if Prophet has no wheel for that image.

`GET /health` returns `{"status":"ok"}` and does not open the database. Use it as the platform health check. A successful health check still leaves `DATABASE_URL` unproved. After the service is up, open `/docs` and request `GET /jobs`.

The API reads these variables when the process starts:

| Variable | On the API host |
| --- | --- |
| `DATABASE_URL` | Required. |
| `CORS_ORIGINS` | Set this to the web app's origin when a browser will call the API. If the variable is unset, every browser origin is allowed. |
| `LOG_LEVEL` | Optional. |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_MIN_SKILLS` | Optional. The read-only API does not call Gemini. Set them on the machine that runs `pipeline.extract_skills`. |
| `SCRAPER_USER_AGENT` | Optional. Set it on the machine that runs scrapers, and include a contact email. |

`API_BASE_URL` is for the Streamlit app. `NEXT_PUBLIC_API_BASE_URL` is for the Next.js app. The API ignores both.

Restart the API after you change `DATABASE_URL` or `CORS_ORIGINS`. `get_settings()` is cached for the life of the process.

### Render

Create a Web Service from this GitHub repository.

- Runtime: Python 3.11.
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`

In the service **Environment** tab, add `DATABASE_URL` and `CORS_ORIGINS`. Add `LOG_LEVEL` if you want it. Save, then deploy from the Render dashboard. Do not put the connection string in the build command.

### Fly.io

Create the app with `fly launch` and inspect the generated files before the first deploy. Point the process at:

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8080
```

Use the same port as the app's internal HTTP port (Fly's generated config often uses 8080). Set `DATABASE_URL` and `CORS_ORIGINS` in the Fly dashboard. Use `GET /health` for the HTTP check.

This repo does not commit a `fly.toml`. Generate it on your account and keep secrets out of it.

### Container

A container is the same install and the same uvicorn command. Pass `DATABASE_URL`, `CORS_ORIGINS`, and `PORT` when the container starts, through the host's environment settings.

This repository does not ship a Dockerfile or a published image. CI installs dependencies and runs tests; it does not build an image. When you write your own image, use Python 3.11, `pip install -r requirements.txt`, and the uvicorn command above. Pass variables in at run time. Build it locally, request `/health` and `/jobs`, and then hand that image to a host.

## Next.js on Vercel

The dashboard is the Next.js app in `web/`. Vercel should use that directory as the project root. The app calls the API from the server on each request (`web/app/page.tsx` is `force-dynamic`), so the API must already have a public URL.

In the Vercel project settings:

- Root Directory: `web`
- Framework Preset: Next.js
- Node.js version: 22 (the version in CI)
- Install command: `npm ci`
- Build command: `npm run build`

`web/` has no `vercel.json`. The preset above matches the CI job, which runs `npm ci`, `npm run lint`, `npm test`, and `npm run build`. The build does not call the API.

In the Vercel **Environment Variables** UI, set `NEXT_PUBLIC_API_BASE_URL` for Production and Preview to the public API origin, with no path and no trailing slash. Redeploy after you change it. Next.js inlines `NEXT_PUBLIC_` variables when the build starts, which is the same rule as local `npm run dev` and `npm run build`.

Leave `DATABASE_URL` and `LLM_API_KEY` off the Vercel project. The web app never opens the database.

The browser loads the Next.js page. The Next.js server calls the API, so that page does not depend on browser CORS. Set `CORS_ORIGINS` on the API when some other browser client, including a future one, will call the API directly. Use the Vercel site origin as that value.

## Streamlit

`streamlit run dashboard/app.py` is a second client. Point `API_BASE_URL` at the deployed API if you run Streamlit yourself. It is not part of the Vercel app.

## Variable names

Set these in the host dashboard that needs them. The table is names only.

| Name | Where to set it |
| --- | --- |
| `DATABASE_URL` | API host, and the machine that migrates or runs the batch |
| `CORS_ORIGINS` | API host |
| `LOG_LEVEL` | API host, optional |
| `LLM_API_KEY` | Batch machine, optional |
| `LLM_MODEL` | Batch machine, optional |
| `LLM_MIN_SKILLS` | Batch machine, optional |
| `SCRAPER_USER_AGENT` | Batch machine, optional |
| `SCRAPER_MIN_DELAY` | Loaded by `config.py`. The site scrapers do not read it. |
| `SCRAPER_MAX_DELAY` | Loaded by `config.py`. The site scrapers do not read it. |
| `API_BASE_URL` | Streamlit host |
| `NEXT_PUBLIC_API_BASE_URL` | Vercel, and local `web/.env.local` |

## After it is up

1. `GET /health` on the API origin.
2. `GET /jobs` and `GET /skills/trends` once the batch has written rows.
3. Open the Vercel URL. The page lists skills, a forecast chart, and roles when the API has those rows. If the API is unreachable, the page says **API not reachable**.

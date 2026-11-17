-- Jobs collected by the scrapers, plus one row per scraper run.

CREATE TABLE IF NOT EXISTS jobs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source text NOT NULL,
    url text NOT NULL UNIQUE,
    title text NOT NULL,
    title_normalized text,
    company text,
    location text,
    salary_min numeric(12, 2),
    salary_max numeric(12, 2),
    description text,
    posted_date date,
    closing_date date,
    content_hash text,
    raw_html_path text,
    scraped_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_content_hash_idx ON jobs (content_hash);

CREATE INDEX IF NOT EXISTS jobs_source_scraped_at_idx ON jobs (source, scraped_at DESC);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    pages integer NOT NULL DEFAULT 0,
    found integer NOT NULL DEFAULT 0,
    inserted integer NOT NULL DEFAULT 0,
    errors integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'running'
);

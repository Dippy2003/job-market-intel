# Web dashboard

Next.js (App Router, TypeScript) view of the read-only Job Market Intelligence API.

The page shows:

- top skills by the latest week of demand (`GET /skills/trends`)
- a trend and forecast chart for the skill you select (`GET /skills/trends`, `GET /skills/forecasts`)
- role clusters, and the jobs in a selected role (`GET /roles`, `GET /roles/{id}`)
- recent postings for the selected skill (`GET /jobs`)

The API has to be running first. From the repository root:

```bash
uvicorn api.main:app
```

Then, in this directory:

```bash
cp .env.example .env.local
npm install
npm run dev
```

Open <http://localhost:3000>. The app calls `NEXT_PUBLIC_API_BASE_URL` from `.env.local` (default `http://127.0.0.1:8000`). That value is not a secret. Do not commit `.env.local`.

Restart `npm run dev` after you change the URL. `NEXT_PUBLIC_` variables are read when the dev server or `npm run build` starts.

```bash
npm test
npm run lint
npm run build
```

`npm test` checks skill ranking and forecast selection offline. It does not call the API.

`npm run build` does not call the API. The page is rendered on each request.

The Next.js server calls the API, so the browser does not need CORS for this page. The API already allows `http://localhost:3000` when `CORS_ORIGINS` lists it, and the default `CORS_ORIGINS=*` allows any origin.

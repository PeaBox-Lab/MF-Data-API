# MF Data API

**Free, open JSON API for Indian mutual fund NAV data** — a self-hostable,
transparent implementation of the familiar `mfapi.in`-style endpoints, built
from the official [AMFI India](https://www.amfiindia.com/net-asset-value/nav-download)
NAV feeds.

- ~14,000 mutual fund schemes, all AMCs and categories
- Full historical NAV series with scheme metadata and ISINs
- No authentication, no API keys, JSON responses
- Daily ingestion via GitHub Actions (twice a day, IST)
- Live FastAPI service **and** a static JSON export for GitHub Pages / any CDN
- Documentation site, interactive API explorer, status page, Swagger UI
- MIT-licensed code; Docker-ready

> This project is independent and is not affiliated with AMFI, SEBI, any AMC or
> mfapi.in. NAV data remains subject to AMFI's and the AMCs' terms.

---

## Contents

- [Architecture](#architecture)
- [Quick start](#quick-start)
- [API](#api)
- [Data pipeline](#data-pipeline)
- [Daily GitHub Actions workflow](#daily-github-actions-workflow)
- [Static JSON mode (GitHub Pages)](#static-json-mode-github-pages)
- [Deployment](#deployment)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Development](#development)
- [Data source & attribution](#data-source--attribution)
- [License](#license)

---

## Architecture

```text
AMFI India                         MF Data API repository
┌──────────────────────┐          ┌───────────────────────────────────────────┐
│ NAVAll.txt           │          │  pipeline/                                │
│ (latest NAVs)        │  daily   │    download → parse → SQLite → JSON       │
│                      │ ───────► │                                           │
│ NAVHistoryReport     │          │  data/mfdata.db  (indexed, WAL)           │
│ (historical, 30-day  │          │  public/api/v1/  (static JSON export)     │
│  chunks)             │          │                                           │
└──────────────────────┘          │  app/  FastAPI  ──►  /api/v1/*            │
                                  │  web/  docs, explorer, status             │
                                  └───────────────────────────────────────────┘
                                              │
                              GitHub Actions ─┴─► GitHub Pages (static JSON)
```

The pipeline stores everything in SQLite for fast querying. The same rows are
exported as per-scheme JSON files, so the project works with or without a
server. The front-end automatically switches between live-API mode and static
mode.

---

## Quick start

### Docker

```bash
docker compose up -d --build
```

- API: <http://localhost:8000/api/v1/mf>
- Docs: <http://localhost:8000/docs>
- Swagger: <http://localhost:8000/api/docs>

On first boot the container downloads the latest NAV file plus 365 days of
history (configurable). The database is kept in the `mfdata` volume.

### Local Python

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt

# 1. Download AMFI data (first run backfills 3 years; use a smaller number for a quick demo)
python -m pipeline sync --bootstrap-days 1095

# 2. Optional: export the static JSON tree
python -m pipeline export --out public

# 3. Run the API + documentation site
python -m pipeline serve --port 8000
```

Open <http://localhost:8000>. The API is also mounted without the version
prefix for compatibility: `/mf/125497/latest`.

### Useful pipeline commands

```bash
python -m pipeline sync --bootstrap-days 30   # small first run
python -m pipeline sync --full                # force a full backfill
python -m pipeline sync --lookback-days 14    # re-check two weeks of corrections
python -m pipeline status                     # counts, freshness, integrity
python -m pipeline export --out public        # static JSON tree
python -m pipeline serve --reload             # development server
```

---

## API

Base URL: `/api/v1` (root-level aliases also work).

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/mf` | Scheme list; `limit`, `offset`, `q`, `fund_house`, `category` |
| `GET` | `/mf/search?q=` | Case-insensitive search, prefix-ranked |
| `GET` | `/mf/{code}` | Metadata + full NAV history, newest first |
| `GET` | `/mf/{code}/latest` | Latest NAV for one scheme |
| `GET` | `/mf/latest` | Latest NAV for every scheme |
| `GET` | `/mf/{code}/meta` | Scheme metadata only |
| `GET` | `/fund-houses` | Fund houses with scheme counts |
| `GET` | `/fund-houses/{name}/schemes` | Schemes for a fund house |
| `GET` | `/categories` | Scheme types/categories with counts |
| `GET` | `/nav/{date}` | All NAVs published on a date |
| `GET` | `/dates` | Recent NAV dates |
| `GET` | `/stats` | Dataset counts and freshness |
| `GET` | `/health` | Health check |

Date inputs accept `YYYY-MM-DD`, `DD-MM-YYYY` or `DD-Mon-YYYY`. Response dates
use `DD-MM-YYYY`; NAVs are fixed-point strings with five decimals.

### Examples

```bash
curl "http://localhost:8000/api/v1/mf/125497/latest"
curl "http://localhost:8000/api/v1/mf/125497?startDate=2025-01-01&endDate=2025-12-31"
curl "http://localhost:8000/api/v1/mf/search?q=hdfc&limit=5"
curl "http://localhost:8000/api/v1/mf?fund_house=SBI%20Mutual%20Fund"
curl "http://localhost:8000/api/v1/nav/20-11-2026?limit=100"
```

```json
{
  "meta": {
    "fund_house": "SBI Mutual Fund",
    "scheme_type": "Open Ended Schemes",
    "scheme_category": "Equity Scheme - Small Cap Fund",
    "scheme_code": 125497,
    "scheme_name": "SBI Small Cap Fund - Direct Plan - Growth",
    "isin_growth": "INF200K01T51",
    "isin_div_reinvestment": null
  },
  "data": [{ "date": "20-11-2026", "nav": "210.02130" }],
  "status": "SUCCESS"
}
```

Full documentation is served at `/docs`, and the generated OpenAPI schema is at
`/api/openapi.json`. Swagger UI is at `/api/docs`.

Rate limiting: 120 requests/minute per IP by default (`MFDATA_RATE_LIMIT`,
`MFDATA_RATE_WINDOW`). CORS is open by default.

---

## Data pipeline

`pipeline/amfi.py` downloads and parses:

1. **Latest NAVs** — `https://portal.amfiindia.com/spages/NAVAll.txt`
2. **Historical NAVs** — `https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx`
   in 30-day chunks (AMFI caps a request at 90 days)

Rows are normalised, de-duplicated on `(scheme_code, date)` and upserted into
SQLite:

- `schemes` — code, name, fund house, type, category, ISINs, latest NAV
- `nav_history` — `(scheme_code, date) → nav`, indexed by date
- `meta` — last sync, dataset dates, counts

The first run backfills `MFDATA_BOOTSTRAP_DAYS` (default 1,095 days). Later runs
re-download a small lookback window (default 7 days) to pick up corrections, plus
the complete latest NAV file.

`pipeline/export_static.py` writes the static API tree:

```text
public/api/v1/
├── mf.json                         # all schemes
├── mf/latest.json                  # latest NAV for every scheme
├── mf/125497.json                  # full history
├── mf/125497/latest.json           # latest for one scheme
├── fund-houses.json
├── categories.json
├── dates.json
├── stats.json
├── meta.json
└── index.json
```

Raw NAVAll snapshots are gzipped into `data/raw/` with a configurable retention
window (default 90 days) for auditing.

---

## Daily GitHub Actions workflow

`.github/workflows/update-data.yml` runs at **09:45 IST** and **22:15 IST**
(plus manual dispatch) and:

1. Restores the SQLite database from the Actions cache.
2. Installs dependencies and runs `python -m pipeline sync`.
3. Exports the static API and copies the documentation site.
4. Saves the database back to the cache and commits `data/status.json`.
5. Uploads the `public/` artifact and deploys GitHub Pages.

### One-time repository setup

1. Push this repository to GitHub.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Actions → Update NAV data → Run workflow** for the first run. A full
   three-year backfill can take a while and downloads several hundred MB from
   AMFI; later runs are incremental.
4. Optional: protect the `main` branch but allow the `github-actions[bot]` to
   push the status commit (or remove the commit step if you prefer).

The workflow needs the default `GITHUB_TOKEN` permissions declared in the file
(`contents: write`, `pages: write`, `id-token: write`).

If the database cache is evicted, the next run automatically performs a full
bootstrap again.

---

## Static JSON mode (GitHub Pages)

`scripts/build_site.py` copies `web/` into `public/` and switches
`assets/config.js` to static mode. The same site then works without any server:

| Live API | Static file |
| --- | --- |
| `/api/v1/mf` | `/api/v1/mf.json` |
| `/api/v1/mf/search?q=` | filter `/api/v1/mf.json` client-side |
| `/api/v1/mf/{code}` | `/api/v1/mf/{code}.json` |
| `/api/v1/mf/{code}/latest` | `/api/v1/mf/{code}/latest.json` |
| `/api/v1/mf/latest` | `/api/v1/mf/latest.json` |
| `/api/v1/fund-houses` | `/api/v1/fund-houses.json` |
| `/api/v1/categories` | `/api/v1/categories.json` |
| `/api/v1/stats` | `/api/v1/stats.json` |
| `/api/v1/nav/{date}` | not available (use per-scheme files) |

The documentation site, search, explorer (with client-side date filtering) and
status page all adapt automatically.

For a local static build:

```bash
python -m pipeline export --out public
python scripts/build_site.py --out public
python -m http.server 8080 --directory public
```

Static exports of full history can be large (hundreds of MB for three years).
Use `python -m pipeline export --out public --history-days 365` if you need a
smaller tree.

---

## Deployment

### Docker / VPS

```bash
docker compose up -d --build
```

Put Nginx/Caddy in front for TLS. Schedule a daily sync on the host:

```bash
docker compose exec api python -m pipeline sync
```

or run the included GitHub Actions workflow and pull the updated database.

### Render / Railway / Fly.io

- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Persistent disk mounted at `/data`; set `MFDATA_DATA_DIR=/data`
- Run `python -m pipeline sync --bootstrap-days 365` once (job or shell), or set
  `MFDATA_AUTO_SYNC=1` and use the Docker entrypoint.

### Static-only (GitHub Pages / S3 / Netlify)

Run the export + build steps and publish `public/`. No Python runtime is needed
at request time.

---

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MFDATA_DATA_DIR` | `./data` | Database and raw snapshots |
| `MFDATA_DB` | `data/mfdata.db` | Explicit SQLite path |
| `MFDATA_BOOTSTRAP_DAYS` | `1095` | History depth for a fresh DB |
| `MFDATA_INCREMENTAL_DAYS` | `7` | Correction window on incremental runs |
| `MFDATA_CHUNK_DAYS` | `30` | History download chunk size (max 90) |
| `MFDATA_RAW_RETENTION_DAYS` | `90` | Keep compressed NAVAll snapshots for N days |
| `MFDATA_RATE_LIMIT` | `120` | Requests per window; `0` disables |
| `MFDATA_RATE_WINDOW` | `60` | Window in seconds |
| `MFDATA_CACHE_TTL` | `300` | Default `Cache-Control` max-age for API responses |
| `MFDATA_CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `MFDATA_AUTO_SYNC` | `1` | Docker: sync automatically when DB is missing |
| `MFDATA_TITLE` / `MFDATA_VERSION` | `MF Data API` / `1.0.0` | Branding |

Copy `.env.example` to `.env` for local use (the app reads environment
variables; it does not load `.env` automatically).

---

## Project structure

```text
.
├── app/                    FastAPI application
│   ├── main.py             app factory, middleware, static site
│   ├── routes.py           all API endpoints
│   ├── schemas.py          Pydantic/OpenAPI models
│   ├── middleware.py       rate limit + cache headers
│   ├── config.py           runtime settings
│   └── deps.py             errors and dependencies
├── pipeline/               AMFI ingestion and storage
│   ├── amfi.py             download + parse NAVAll/history feeds
│   ├── store.py            SQLite schema, upserts, queries
│   ├── sync.py             daily sync orchestration
│   ├── export_static.py    static JSON export
│   ├── config.py           pipeline settings
│   ├── dates.py            date helpers
│   └── __main__.py         `python -m pipeline` CLI
├── web/                    documentation site (no build step)
│   ├── index.html          landing page
│   ├── docs.html           full API documentation
│   ├── explorer.html       interactive request builder
│   ├── status.html         dataset/status page
│   └── assets/             CSS, JS, config, favicon
├── scripts/build_site.py   copy site + static config for Pages
├── docker/entrypoint.sh    Docker entrypoint with optional first sync
├── tests/                  parser, store, API, export tests
├── .github/workflows/      daily data update + CI
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Development

```bash
pip install -r requirements-dev.txt
ruff check app pipeline tests scripts
pytest -q
```

Tests use small AMFI fixtures, so they run offline and do not touch the network.

The web UI has no build step — plain HTML/CSS/JS. Edit files in `web/` and reload.
When served by FastAPI, `/docs`, `/explorer`, `/status`, `/privacy` and `/terms`
map to the corresponding HTML files.

---

## Data source & attribution

- Latest NAVs: <https://portal.amfiindia.com/spages/NAVAll.txt>
- Historical NAVs: <https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx>
- AMFI NAV download page: <https://www.amfiindia.com/net-asset-value/nav-download>

AMFI is the official source of Indian mutual fund NAVs. Scheme names,
categories, ISINs and NAV values are reproduced as published. The project is not
affiliated with AMFI, SEBI or any asset management company. Verify data against
the official source before using it for financial decisions.

## License

Code: [MIT](LICENSE). Data: subject to AMFI's and the AMCs' terms; attribution to
AMFI India is required when redistributing.

Built by PeaBox Labs
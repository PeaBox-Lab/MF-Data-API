"""Export the SQLite store as static, mfapi-compatible JSON files.

The export is used for GitHub Pages / any static host. The FastAPI service
serves the same payloads directly from SQLite.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from .analytics import (
    LEVELS,
    all_movement_payload,
    groups_payload,
    has_analytics,
    summary_payload,
)
from .config import Settings, load_settings
from .dates import to_api_date, utc_now_iso
from .store import Store

VERSION = "1.0.0"

# ------------------------------------------------------------------ data sources
# Curated list of free, open mutual fund / ETF / fund data APIs worldwide.
# Static JSON export keeps this available for static (GitHub Pages) deployments.
DATA_SOURCES = [
    {
        "name": "MF Data API (this project)",
        "region": "India",
        "coverage": "Indian mutual fund NAVs + scheme metadata (AMFI source).",
        "auth": "None — no key or registration",
        "rate_limit": "120 req/min per IP (live service); static JSON is uncapped",
        "base_url": "https://peabox-lab.github.io/MF-Data-API/api/v1",
        "docs_url": "https://peabox-lab.github.io/MF-Data-API/docs.html",
        "notes": "Live FastAPI service plus static JSON export for GitHub Pages.",
    },
    {
        "name": "MFapi.in",
        "region": "India",
        "coverage": "Indian mutual fund search, latest NAV, and NAV history.",
        "auth": "None (per documentation)",
        "rate_limit": "Not documented — documented as no rate limits",
        "base_url": "https://api.mfapi.in/mf",
        "docs_url": "https://www.mfapi.in/docs",
        "notes": "Largest dedicated Indian NAV API; updated up to 6x daily.",
    },
    {
        "name": "mfdata.in",
        "region": "India",
        "coverage": "Indian NAV, portfolio holdings, sector analysis, ratios, returns (14,000+ schemes, 51 AMCs).",
        "auth": "None required",
        "rate_limit": "Standard 30/min; analytics 10/min; bulk 10/min",
        "base_url": "https://api.mfdata.in/api/v1",
        "docs_url": "https://mfdata.in/docs",
        "notes": "Deep per-scheme enrichment: holdings, risk metrics, sector allocation.",
    },
    {
        "name": "Charlie API (charliealpha.in)",
        "region": "India",
        "coverage": "Indian mutual funds & ETFs, NPS, SIF, GIFT City funds — latest/historical NAV, holdings.",
        "auth": "Unauthenticated",
        "rate_limit": "50 req / 10 s",
        "base_url": "https://api.charliealpha.in/v1",
        "docs_url": "https://api.charliealpha.in/v1",
        "notes": "GET-only endpoints; accepts AMFI scheme code or ISIN.",
    },
    {
        "name": "mfnav.in",
        "region": "India",
        "coverage": "Indian NAV history from Jan 2006 (38,000+ schemes, 76 fund houses).",
        "auth": "None",
        "rate_limit": "120 req/min per IP",
        "base_url": "https://mfnav.in/api",
        "docs_url": "https://mfnav.in/api-docs",
        "notes": "Free for any use including commercial; sync your own mirror daily.",
    },
    {
        "name": "TickerInside",
        "region": "USA (ETFs)",
        "coverage": "US ETFs + large US mutual funds — portfolio holdings, overlap, holders.",
        "auth": "None — no key, no account, no quota",
        "rate_limit": "None for normal use",
        "base_url": "https://tickerinside.com/api/v1",
        "docs_url": "https://tickerinside.com/api",
        "notes": "CC BY 4.0. Derived from issuer holdings files and SEC Form N-PORT.",
    },
    {
        "name": "FundCensus",
        "region": "USA",
        "coverage": "US registered fund (mutual/ETF/CEF) holdings — Form N-PORT positions.",
        "auth": "Key optional (authenticated raises daily allowance)",
        "rate_limit": "Unauthenticated: per-IP limits, lists stop at first 500 rows",
        "base_url": "https://fundcensus.com/api",
        "docs_url": "https://fundcensus.com/openapi.json",
        "notes": "Holdings are quarterly snapshots (~60 days lag).",
    },
    {
        "name": "Leeway Fonds-API",
        "region": "Europe + USA",
        "coverage": "40,000+ European funds NAV & reference data via ISIN; US funds with holdings, TER, returns.",
        "auth": "Free account token",
        "rate_limit": "50 requests/day (free account)",
        "base_url": "https://api.leeway.tech/api/v1",
        "docs_url": "https://leeway.tech/data-api/fonds",
        "notes": "Free tier is non-commercial use.",
    },
    {
        "name": "Tigzig Public APIs",
        "region": "India + Global macro",
        "coverage": "AMFI MF NAV history (38,000+ schemes since April 2006); global macro indicators (~300).",
        "auth": "None",
        "rate_limit": "Not documented",
        "base_url": "https://api.tigzig.com/v1",
        "docs_url": "https://www.tigzig.com/apis",
        "notes": "CSV / TSV / Parquet / SQLite bulk downloads.",
    },
    {
        "name": "Pakistan Mutual Funds (MUFAP-based)",
        "region": "Pakistan",
        "coverage": "~550 Pakistani mutual funds — daily NAV, dividends, indices.",
        "auth": "No signup / no API key (flat files + hosted REST API)",
        "rate_limit": "Not documented",
        "base_url": "https://github.com/saadsalmankhan/pakistan-mutual-funds-data",
        "docs_url": "https://saadsalman.org/projects/pakistan-mutual-funds",
        "notes": "Open dataset; not affiliated with MUFAP.",
    },
    {
        "name": "Market Data (api.marketdata.app)",
        "region": "USA",
        "coverage": "US mutual fund candlestick / OHLC historical data.",
        "auth": "Free trial account (no card)",
        "rate_limit": "100 requests/day on free tier",
        "base_url": "https://api.marketdata.app/v1",
        "docs_url": "https://www.marketdata.app/api/funds/how-to-use/",
        "notes": "Free plan is for personal use.",
    },
    {
        "name": "iTick Mutual Funds API",
        "region": "Global (focus: funds/ETFs)",
        "coverage": "Mutual funds, ETFs — end-of-day and historical data.",
        "auth": "Free plan (personal use only)",
        "rate_limit": "5 calls/minute free plan",
        "base_url": "https://itick.org/en/products/fund",
        "docs_url": "https://itick.org/en/products/fund",
        "notes": "Free tier restricted to personal use.",
    },
    {
        "name": "SEC EDGAR (via edgartools)",
        "region": "USA",
        "coverage": "US mutual fund / ETF holdings from Form N-PORT filings — every position.",
        "auth": "None",
        "rate_limit": "None (public EDGAR)",
        "base_url": "https://www.sec.gov/edgar",
        "docs_url": "https://edgartools.readthedocs.io",
        "notes": "US government work — public domain; monthly N-PORT holdings with lag.",
    },
    {
        "name": "ESMA Registers",
        "region": "Europe (EU)",
        "coverage": "EU investment fund / AIFMD registers — authorised funds & managers.",
        "auth": "None",
        "rate_limit": "Not documented",
        "base_url": "https://registers.esma.europa.eu/publication/solr/esma_registers_*",
        "docs_url": "https://www.esma.europa.eu/publications-and-data/databases-and-registers",
        "notes": "Reference registers rather than daily NAV feed.",
    },
    {
        "name": "Info-financiere.gouv.fr API",
        "region": "France",
        "coverage": "French regulated financial information (stock market, funds).",
        "auth": "Not documented",
        "rate_limit": "Not documented",
        "base_url": "https://info-financiere.gouv.fr/pages/api0/",
        "docs_url": "https://info-financiere.gouv.fr/pages/api0/",
        "notes": "French official centralised mechanism.",
    },
]


def _write_json(path: Path, payload, *, compact: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def _meta_payload(meta: dict) -> dict:
    return {
        "fund_house": meta.get("fund_house", ""),
        "scheme_type": meta.get("scheme_type", ""),
        "scheme_category": meta.get("scheme_category", ""),
        "scheme_code": meta.get("scheme_code"),
        "scheme_name": meta.get("scheme_name", ""),
        "isin_growth": meta.get("isin_growth"),
        "isin_div_reinvestment": meta.get("isin_div_reinvestment"),
    }


def _history_payload(meta: dict, rows: list[tuple[str, float]]) -> dict:
    return {
        "meta": _meta_payload(meta),
        "data": [{"date": to_api_date(day), "nav": f"{nav:.5f}"} for day, nav in rows],
        "status": "SUCCESS",
    }


def export_static(
    settings: Settings | None = None,
    *,
    out_dir: Path | str = "public",
    history_days: int | None = None,
    include_latest: bool = True,
    analytics_days: int | None = 365,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    """Write the full static API tree under ``out_dir/api/v1``."""

    settings = settings or load_settings()
    log_fn = log_fn or print
    out_dir = Path(out_dir)
    api_dir = out_dir / "api" / "v1"

    store = Store(settings.db_path)
    if not store.has_data():
        raise RuntimeError(
            f"No NAV data found at {settings.db_path}. Run 'python -m pipeline sync' first."
        )

    generated_at = utc_now_iso()
    counts = store.counts()
    meta_map = {scheme["scheme_code"]: scheme for scheme in store.iter_schemes()}
    start_iso = (
        (date.today() - timedelta(days=history_days)).isoformat()
        if history_days
        else None
    )

    log_fn(f"Exporting static API to {api_dir}")
    schemes = store.list_schemes()
    _write_json(api_dir / "mf.json", schemes)
    log_fn(f"  mf.json: {len(schemes):,} schemes")

    browse = store.browse_schemes()
    _write_json(api_dir / "mf" / "browse.json", browse)
    log_fn(f"  mf/browse.json: {len(browse):,} schemes")

    latest = store.latest_all()
    latest_payload = [
        {
            "schemeCode": row["schemeCode"],
            "schemeName": row["schemeName"],
            "nav": row["nav"],
            "date": to_api_date(row["date"]),
        }
        for row in latest
    ]
    _write_json(api_dir / "mf" / "latest.json", latest_payload)
    log_fn(f"  mf/latest.json: {len(latest_payload):,} rows")

    written = 0
    for code, rows in store.iter_histories():
        if start_iso:
            rows = [row for row in rows if row[0] >= start_iso]
        if not rows:
            continue
        meta = meta_map.get(code)
        if meta is None:
            continue
        _write_json(api_dir / "mf" / f"{code}.json", _history_payload(meta, rows))
        if include_latest:
            _write_json(
                api_dir / "mf" / str(code) / "latest.json",
                _history_payload(meta, rows[:1]),
            )
        written += 1
        if written % 1000 == 0:
            log_fn(f"  exported {written:,} scheme files...")

    stats = {
        "generated_at": generated_at,
        "latest_nav_date": to_api_date(counts["latest_date"]) if counts.get("latest_date") else None,
        "earliest_nav_date": to_api_date(counts["earliest_date"]) if counts.get("earliest_date") else None,
        "scheme_count": counts.get("scheme_count", 0),
        "nav_rows": counts.get("nav_rows", 0),
        "fund_house_count": counts.get("fund_house_count", 0),
        "category_count": counts.get("category_count", 0),
        "source": "AMFI India",
        "source_url": "https://www.amfiindia.com/net-asset-value/nav-download",
        "database_bytes": store.db_size_bytes(),
    }
    _write_json(api_dir / "stats.json", stats, compact=False)
    _write_json(api_dir / "fund-houses.json", store.fund_houses(), compact=False)
    _write_json(api_dir / "categories.json", store.categories(), compact=False)
    _write_json(api_dir / "dates.json", [to_api_date(day) for day in store.nav_dates(60)], compact=False)
    _write_json(api_dir / "meta.json", store.get_meta(), compact=False)
    _write_json(
        api_dir / "index.json",
        {
            "name": "MF Data API",
            "version": VERSION,
            "generated_at": generated_at,
            "docs": "docs/",
            "scheme_files": written,
            "endpoints": {
                "all_schemes": "mf.json",
                "latest_navs": "mf/latest.json",
                "scheme_history": "mf/{scheme_code}.json",
                "scheme_latest": "mf/{scheme_code}/latest.json",
                "stats": "stats.json",
                "fund_houses": "fund-houses.json",
                "categories": "categories.json",
                "recent_dates": "dates.json",
                "health": "health.json",
                "movers": "movers.json",
                "data_sources": "data-sources.json",
                "analytics_summary": "analytics/summary.json",
                "analytics_groups": "analytics/groups.json",
                "analytics_movement": "analytics/movement.json",
            },
        },
        compact=False,
    )

    # Health check payload (mirrors live /health endpoint)
    meta = store.get_meta()
    health = {
        "status": "ok",
        "database": "ok",
        "latest_nav_date": to_api_date(counts["latest_date"]) if counts.get("latest_date") else None,
        "last_sync": meta.get("last_sync"),
        "scheme_count": counts.get("scheme_count", 0),
    }
    _write_json(api_dir / "health.json", health, compact=False)

    # ---------------------------------------------------------------- extras
    # Top movers (computed once at export time)
    movers = store.movers(limit=50)
    _write_json(api_dir / "movers.json", {"data": movers, "count": len(movers)}, compact=False)

    # Curated directory of free mutual fund data APIs worldwide
    _write_json(api_dir / "data-sources.json", DATA_SOURCES, compact=False)

    # Pre-computed daily movement analytics (when calc_analytics.py has run).
    analytics_count = 0
    with store.connect(readonly=True) as conn:
        if has_analytics(conn):
            analytics_dir = api_dir / "analytics"
            start_iso = (
                (date.today() - timedelta(days=analytics_days)).isoformat()
                if analytics_days
                else None
            )
            _write_json(
                analytics_dir / "summary.json", summary_payload(conn), compact=False
            )
            _write_json(
                analytics_dir / "groups.json",
                {level: groups_payload(conn, level) for level in LEVELS},
                compact=False,
            )
            movement = all_movement_payload(conn, start=start_iso)
            _write_json(analytics_dir / "movement.json", movement)
            analytics_count = len(movement)
            log_fn(f"  analytics/movement.json: {analytics_count:,} group/date rows")
        else:
            log_fn("  analytics: skipped (run scripts/calc_analytics.py to enable)")

    log_fn(f"Exported {written:,} scheme histories in {out_dir}")
    return {
        "out_dir": str(out_dir),
        "schemes": len(schemes),
        "scheme_files": written,
        "latest_rows": len(latest),
        "movers": len(movers),
        "data_sources": len(DATA_SOURCES),
        "analytics_rows": analytics_count,
        "generated_at": generated_at,
    }

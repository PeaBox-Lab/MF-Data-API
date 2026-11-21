"""Export the SQLite store as static, mfapi-compatible JSON files.

The export is used for GitHub Pages / any static host. The FastAPI service
serves the same payloads directly from SQLite.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from .config import Settings, load_settings
from .dates import to_api_date, utc_now_iso
from .store import Store

VERSION = "1.0.0"


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
            },
        },
        compact=False,
    )

    log_fn(f"Exported {written:,} scheme histories in {out_dir}")
    return {
        "out_dir": str(out_dir),
        "schemes": len(schemes),
        "scheme_files": written,
        "latest_rows": len(latest),
        "generated_at": generated_at,
    }

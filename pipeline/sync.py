"""Daily synchronisation of AMFI NAV data into the local SQLite store."""

from __future__ import annotations

import gzip
import json
import logging
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from . import amfi
from .config import Settings, load_settings
from .dates import date_chunks, from_iso, to_iso, utc_now_iso
from .store import Store

log = logging.getLogger(__name__)


def _save_raw(settings: Settings, text: str, day: date) -> Path:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    path = settings.raw_dir / f"navall-{to_iso(day)}.txt.gz"
    with gzip.open(path, "wb", compresslevel=9) as handle:
        handle.write(text.encode("utf-8"))
    return path


def _prune_raw(settings: Settings) -> int:
    if settings.raw_retention_days <= 0:
        return 0
    cutoff = date.today() - timedelta(days=settings.raw_retention_days)
    removed = 0
    for path in settings.raw_dir.glob("navall-*.txt.gz"):
        try:
            day_str = path.name[len("navall-") : -len(".txt.gz")]
            day = date.fromisoformat(day_str)
        except ValueError:
            continue
        if day < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def sync(
    settings: Settings | None = None,
    *,
    bootstrap_days: int | None = None,
    lookback_days: int | None = None,
    full: bool = False,
    save_raw: bool = True,
    strict: bool = False,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    """Fetch the latest NAV file plus recent history and update the database.

    ``full`` forces a backfill of ``bootstrap_days`` even when the database
    already contains data. Otherwise the history download starts from the most
    recent stored date minus ``lookback_days`` (to pick up corrections).
    """

    settings = settings or load_settings()
    settings.ensure_dirs()
    bootstrap_days = bootstrap_days or settings.bootstrap_days
    lookback_days = settings.incremental_days if lookback_days is None else lookback_days
    log_fn = log_fn or log.info
    started = time.monotonic()
    today = date.today()

    store = Store(settings.db_path)
    store.init_schema()

    latest_before = store.max_nav_date()
    is_initial = full or not latest_before
    log_fn(f"Database: {settings.db_path}")
    log_fn(f"Mode: {'initial backfill' if is_initial else 'incremental update'}")

    # ---------------------------------------------------------- latest NAVAll
    log_fn("Downloading NAVAll.txt ...")
    navall = amfi.fetch_navall(settings, log_fn=log_fn)
    raw_path = _save_raw(settings, navall, today) if save_raw else None
    if raw_path:
        log_fn(f"Saved raw snapshot: {raw_path.name} ({raw_path.stat().st_size:,} bytes)")

    navall_stats = store.ingest(amfi.parse_navall(navall), log_fn=log_fn)
    log_fn(
        f"NAVAll parsed: {navall_stats['rows']:,} rows across "
        f"{navall_stats['schemes']:,} schemes"
    )

    # ------------------------------------------------------------ NAV history
    if is_initial:
        history_start = today - timedelta(days=bootstrap_days)
    else:
        history_start = max(
            today - timedelta(days=bootstrap_days),
            from_iso(latest_before) - timedelta(days=lookback_days),
        )

    chunks = date_chunks(history_start, today, settings.chunk_days)
    log_fn(
        f"History range: {to_iso(history_start)} to {to_iso(today)} "
        f"({len(chunks)} chunk(s))"
    )

    history_rows = 0
    errors: list[str] = []
    for index, (start, end) in enumerate(chunks, start=1):
        log_fn(f"  [{index}/{len(chunks)}] {to_iso(start)} .. {to_iso(end)}")
        try:
            text = amfi.fetch_history(settings, start, end, log_fn=log_fn)
            stats = store.ingest(amfi.parse_history(text), log_fn=log_fn)
            history_rows += stats["rows"]
            log_fn(f"    {stats['rows']:,} rows, {stats['schemes']:,} schemes")
        except Exception as exc:  # noqa: BLE001 - reported and optionally raised
            message = f"{to_iso(start)}..{to_iso(end)}: {exc}"
            errors.append(message)
            log_fn(f"    WARNING: {message}")
            if strict:
                raise

    if errors and len(errors) == len(chunks):
        raise RuntimeError("Every NAV history chunk failed: " + "; ".join(errors))

    # --------------------------------------------------------------- finalise
    log_fn("Refreshing latest NAV columns ...")
    store.refresh_latest()
    counts = store.counts()
    duration = round(time.monotonic() - started, 1)
    finished_at = utc_now_iso()

    meta = {
        "last_sync": finished_at,
        "last_sync_date": to_iso(today),
        "latest_nav_date": counts.get("latest_date") or "",
        "earliest_nav_date": counts.get("earliest_date") or "",
        "scheme_count": str(counts.get("scheme_count", 0)),
        "nav_rows": str(counts.get("nav_rows", 0)),
        "fund_house_count": str(counts.get("fund_house_count", 0)),
        "category_count": str(counts.get("category_count", 0)),
        "source": "AMFI India",
        "source_url": "https://www.amfiindia.com/net-asset-value/nav-download",
        "last_sync_errors": " | ".join(errors),
    }
    store.set_meta(meta)

    status = {
        "generated_at": finished_at,
        "duration_seconds": duration,
        "mode": "full" if is_initial else "incremental",
        "latest_nav_date": counts.get("latest_date"),
        "earliest_nav_date": counts.get("earliest_date"),
        "scheme_count": counts.get("scheme_count", 0),
        "nav_rows": counts.get("nav_rows", 0),
        "fund_house_count": counts.get("fund_house_count", 0),
        "navall_rows": navall_stats["rows"],
        "history_rows": history_rows,
        "history_chunks": len(chunks),
        "errors": errors,
        "database_bytes": store.db_size_bytes(),
        "source": "AMFI India",
    }
    settings.status_path.write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if save_raw:
        removed = _prune_raw(settings)
        if removed:
            log_fn(f"Pruned {removed} old raw snapshot(s)")

    log_fn(
        f"Done in {duration}s: {counts.get('scheme_count', 0):,} schemes, "
        f"{counts.get('nav_rows', 0):,} NAV rows, latest {counts.get('latest_date')}"
    )
    return status


def main() -> None:  # pragma: no cover - convenience entry point
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sync(log_fn=print)


if __name__ == "__main__":  # pragma: no cover
    main()

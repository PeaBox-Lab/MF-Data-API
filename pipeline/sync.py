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


CHECKPOINT_KEY = "sync_completed_chunks"
ANCHOR_KEY = "sync_checkpoint_anchor"
CHECKPOINT_CHUNK_DAYS_KEY = "sync_checkpoint_chunk_days"


def _load_checkpoint(store: Store) -> set[tuple[str, str]]:
    """Return the date windows already committed in a previous run."""
    raw = store.get_meta().get(CHECKPOINT_KEY, "")
    try:
        values = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return set()
    return {
        (item[0], item[1])
        for item in values
        if isinstance(item, (list, tuple))
        and len(item) == 2
        and isinstance(item[0], str)
        and isinstance(item[1], str)
    }


def _save_checkpoint(store: Store, done: set[tuple[str, str]]) -> None:
    store.set_meta(
        {CHECKPOINT_KEY: json.dumps(sorted([list(item) for item in done]))}
    )


def checkpoint_chunk_days(settings: Settings | None = None) -> int:
    """Return the chunk size recorded for the current backfill checkpoint."""

    settings = settings or load_settings()
    store = Store(settings.db_path)
    if not store.path.exists():
        return settings.chunk_days
    raw = store.get_meta().get(CHECKPOINT_CHUNK_DAYS_KEY, "")
    try:
        return max(1, min(90, int(raw))) if raw else settings.chunk_days
    except ValueError:
        return settings.chunk_days


def pending_chunks(
    settings: Settings | None = None,
    *,
    bootstrap_days: int | None = None,
    chunk_days: int | None = None,
    reset: bool = False,
) -> list[tuple[date, date]]:
    """Return the not-yet-completed chunks of a stable backfill window.

    The first chunk boundary is stored in the database so that new days append
    new chunks instead of shifting every boundary and invalidating the
    checkpoint. ``reset=True`` starts a fresh anchored window.
    """

    settings = settings or load_settings()
    settings.ensure_dirs()
    bootstrap_days = bootstrap_days or settings.bootstrap_days
    chunk_days = settings.chunk_days if chunk_days is None else max(1, min(90, chunk_days))
    today = date.today()

    store = Store(settings.db_path)
    store.init_schema()
    meta = store.get_meta()

    if reset:
        store.set_meta(
            {
                CHECKPOINT_KEY: "[]",
                ANCHOR_KEY: "",
                CHECKPOINT_CHUNK_DAYS_KEY: "",
            }
        )
        meta = store.get_meta()

    anchor = meta.get(ANCHOR_KEY, "")
    if anchor:
        history_start = from_iso(anchor)
        stored_chunk_days = meta.get(CHECKPOINT_CHUNK_DAYS_KEY, "")
        if stored_chunk_days:
            try:
                chunk_days = max(1, min(90, int(stored_chunk_days)))
            except ValueError:
                pass
    else:
        history_start = today - timedelta(days=bootstrap_days)
        store.set_meta(
            {
                ANCHOR_KEY: to_iso(history_start),
                CHECKPOINT_CHUNK_DAYS_KEY: str(chunk_days),
            }
        )

    done = _load_checkpoint(store)
    return [
        chunk
        for chunk in date_chunks(history_start, today, chunk_days)
        if (to_iso(chunk[0]), to_iso(chunk[1])) not in done
    ]


def sync(
    settings: Settings | None = None,
    *,
    bootstrap_days: int | None = None,
    lookback_days: int | None = None,
    full: bool = False,
    save_raw: bool = True,
    strict: bool = False,
    log_fn: Callable[[str], None] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    skip_navall: bool = False,
    finalise: bool = True,
    chunk_days: int | None = None,
) -> dict:
    """Fetch the latest NAV file plus recent history and update the database.

    ``full`` forces a backfill of ``bootstrap_days`` even when the database
    already contains data. Otherwise the history download starts from the most
    recent stored date minus ``lookback_days`` (to pick up corrections).

    Passing ``start_date``/``end_date`` switches to *window mode*: only that
    bounded range is fetched, NAVAll can be skipped, and completed chunks are
    recorded in the ``sync_completed_chunks`` metadata key. Re-running the same
    window resumes from the first unfinished chunk. This lets a long backfill
    be split into small, independently bounded jobs.
    """

    settings = settings or load_settings()
    settings.ensure_dirs()
    bootstrap_days = bootstrap_days or settings.bootstrap_days
    lookback_days = settings.incremental_days if lookback_days is None else lookback_days
    chunk_days = settings.chunk_days if chunk_days is None else max(1, min(90, chunk_days))
    window_mode = start_date is not None or end_date is not None
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
    if skip_navall:
        log_fn("Skipping NAVAll.txt (window mode)")
        navall_stats = {"rows": 0, "schemes": 0}
    else:
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
    if window_mode:
        history_start = start_date or today
        history_end = end_date or today
        if history_start > history_end:
            raise ValueError("start_date must not be after end_date")
    else:
        history_end = today
        if is_initial:
            history_start = today - timedelta(days=bootstrap_days)
        else:
            history_start = max(
                today - timedelta(days=bootstrap_days),
                from_iso(latest_before) - timedelta(days=lookback_days),
            )

    chunks = date_chunks(history_start, history_end, chunk_days)
    log_fn(
        f"History range: {to_iso(history_start)} to {to_iso(history_end)} "
        f"({len(chunks)} chunk(s), {chunk_days} days each)"
    )

    done = _load_checkpoint(store) if window_mode else set()
    history_rows = 0
    errors: list[str] = []
    skipped = 0
    for index, (start, end) in enumerate(chunks, start=1):
        key = (to_iso(start), to_iso(end))
        if window_mode and key in done:
            skipped += 1
            log_fn(f"  [{index}/{len(chunks)}] {key[0]} .. {key[1]} (done)")
            continue
        log_fn(f"  [{index}/{len(chunks)}] {key[0]} .. {key[1]}")
        try:
            text = amfi.fetch_history(settings, start, end, log_fn=log_fn)
            stats = store.ingest(amfi.parse_history(text), log_fn=log_fn)
            history_rows += stats["rows"]
            log_fn(f"    {stats['rows']:,} rows, {stats['schemes']:,} schemes")
            if window_mode:
                done.add(key)
                _save_checkpoint(store, done)
        except Exception as exc:  # noqa: BLE001 - reported and optionally raised
            message = f"{key[0]}..{key[1]}: {exc}"
            errors.append(message)
            log_fn(f"    WARNING: {message}")
            if strict:
                raise

    attempted = len(chunks) - skipped
    if errors and attempted and len(errors) == attempted:
        raise RuntimeError("Every NAV history chunk failed: " + "; ".join(errors))

    # --------------------------------------------------------------- finalise
    duration = round(time.monotonic() - started, 1)
    finished_at = utc_now_iso()

    if not finalise:
        status = {
            "generated_at": finished_at,
            "duration_seconds": duration,
            "mode": "window",
            "window_start": to_iso(history_start),
            "window_end": to_iso(history_end),
            "chunks": len(chunks),
            "chunks_completed": len(chunks) - skipped - len(errors),
            "errors": errors,
        }
        log_fn(
            f"Window {status['window_start']}..{status['window_end']} done in "
            f"{duration}s ({status['chunks_completed']}/{len(chunks)} chunks)."
        )
        return status

    log_fn("Refreshing latest NAV columns ...")
    store.refresh_latest()
    counts = store.counts()

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
        "mode": "window" if window_mode else ("full" if is_initial else "incremental"),
        "latest_nav_date": counts.get("latest_date"),
        "earliest_nav_date": counts.get("earliest_date"),
        "scheme_count": counts.get("scheme_count", 0),
        "nav_rows": counts.get("nav_rows", 0),
        "fund_house_count": counts.get("fund_house_count", 0),
        "navall_rows": navall_stats["rows"],
        "history_rows": history_rows,
        "history_chunks": len(chunks),
        "history_chunks_skipped": skipped,
        "errors": errors,
        "database_bytes": store.db_size_bytes(),
        "source": "AMFI India",
    }
    if window_mode:
        status.update(
            {
                "window_start": to_iso(history_start),
                "window_end": to_iso(history_end),
                "chunks": len(chunks),
                "chunks_completed": len(chunks) - skipped - len(errors),
                "chunks_pending": sum(
                    1 for chunk in chunks if (to_iso(chunk[0]), to_iso(chunk[1])) not in done
                ),
            }
        )
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

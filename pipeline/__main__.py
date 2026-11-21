"""Command line interface for the MF Data API pipeline.

Examples
--------
    python -m pipeline sync --bootstrap-days 1095
    python -m pipeline sync --full --lookback-days 14
    python -m pipeline export --out public
    python -m pipeline status
    python -m pipeline serve --port 8000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from .config import Settings, load_settings
from .export_static import export_static
from .store import Store
from .sync import sync


def _settings(args: argparse.Namespace) -> Settings:
    settings = load_settings()
    data_dir = Path(args.data_dir).expanduser().resolve() if args.data_dir else settings.data_dir
    db_override = Path(args.db).expanduser().resolve() if args.db else settings.db_override
    return replace(settings, data_dir=data_dir, db_override=db_override)


def _print_json(payload) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_sync(args: argparse.Namespace) -> int:
    settings = _settings(args)
    summary = sync(
        settings,
        bootstrap_days=args.bootstrap_days,
        lookback_days=args.lookback_days,
        full=args.full,
        save_raw=not args.no_raw,
        strict=args.strict,
        log_fn=print,
    )
    _print_json(summary)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    settings = _settings(args)
    summary = export_static(
        settings,
        out_dir=args.out,
        history_days=args.history_days,
        include_latest=not args.no_latest,
        log_fn=print,
    )
    _print_json(summary)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = _settings(args)
    store = Store(settings.db_path)
    if not store.has_data():
        print(f"No database found at {settings.db_path}", file=sys.stderr)
        return 1
    counts = store.counts()
    meta = store.get_meta()
    _print_json(
        {
            "database": str(settings.db_path),
            "database_bytes": store.db_size_bytes(),
            "integrity": store.integrity_check(),
            "counts": counts,
            "latest_nav_date": counts.get("latest_date"),
            "last_sync": meta.get("last_sync"),
            "raw_snapshots": len(list(settings.raw_dir.glob("*.txt.gz"))),
        }
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    settings = _settings(args)
    os.environ["MFDATA_DATA_DIR"] = str(settings.data_dir)
    if settings.db_override:
        os.environ["MFDATA_DB"] = str(settings.db_override)

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mfdata",
        description="Build and serve the MF Data API from AMFI India NAV feeds.",
    )
    parser.add_argument("--data-dir", help="Data directory (default: ./data)")
    parser.add_argument("--db", help="Explicit SQLite database path")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_parser = sub.add_parser("sync", help="Download AMFI data and update the database")
    sync_parser.add_argument(
        "--bootstrap-days",
        type=int,
        help="Days of history to download on the first run (default: 1095)",
    )
    sync_parser.add_argument(
        "--lookback-days",
        type=int,
        help="Days to re-download on incremental runs (default: 7)",
    )
    sync_parser.add_argument(
        "--full", action="store_true", help="Force a full history backfill"
    )
    sync_parser.add_argument(
        "--no-raw", action="store_true", help="Do not keep compressed NAVAll snapshots"
    )
    sync_parser.add_argument(
        "--strict", action="store_true", help="Fail on the first history chunk error"
    )
    sync_parser.set_defaults(func=cmd_sync)

    export_parser = sub.add_parser("export", help="Write the static JSON API tree")
    export_parser.add_argument(
        "--out", default="public", help="Output directory (default: public)"
    )
    export_parser.add_argument(
        "--history-days",
        type=int,
        help="Only export the most recent N days of history",
    )
    export_parser.add_argument(
        "--no-latest", action="store_true", help="Skip per-scheme latest.json files"
    )
    export_parser.set_defaults(func=cmd_export)

    status_parser = sub.add_parser("status", help="Show database statistics")
    status_parser.set_defaults(func=cmd_status)

    serve_parser = sub.add_parser("serve", help="Run the FastAPI service")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")
    serve_parser.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

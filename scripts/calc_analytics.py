"""Recalculate daily NAV-movement analytics from the SQLite database.

Usage:
    python scripts/calc_analytics.py [--db-path data/mfdata.db] [--max-gap-days 4]
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.analytics import (  # noqa: E402
    DEFAULT_MAX_GAP_DAYS,
    compute_daily_returns,
    compute_group_daily,
    write_analytics,
)
from pipeline.config import load_settings  # noqa: E402

log = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=None,
        help="SQLite database (default: MFDATA_DB or data/mfdata.db)",
    )
    parser.add_argument(
        "--max-gap-days",
        type=int,
        default=DEFAULT_MAX_GAP_DAYS,
        help="Maximum calendar-day gap between NAVs counted as a daily move",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args()
    db_path = Path(args.db_path) if args.db_path else load_settings().db_path
    if not db_path.exists():
        log.error("Database not found: %s", db_path)
        raise SystemExit(1)
    if args.max_gap_days < 1:
        log.error("--max-gap-days must be at least 1")
        raise SystemExit(1)

    log.info("Connecting to database: %s", db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        returns = compute_daily_returns(conn, max_gap_days=args.max_gap_days)
        groups = compute_group_daily(returns)
        families = len({row["family_code"] for row in returns})
        log.info(
            "Computed movement: %d scheme returns across %d fund families; "
            "%d group/date rows",
            len(returns),
            families,
            len(groups),
        )
        write_analytics(conn, returns, groups, max_gap_days=args.max_gap_days)
        log.info("Analytics tables written successfully.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

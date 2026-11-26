"""Recalculate KPI tables from NAV data.

Reads scheme metadata + NAV history from the SQLite database and recomputes
aggregate KPIs at scheme, fund-house, category, and fund-type levels.
Results are written back to scheme_kpis, fund_house_kpis, category_kpis,
type_kpis tables.

Usage:
    python scripts/calc_kpis.py [--db-path path/to/mfapi.db]
"""

from __future__ import annotations

import argparse
import logging
import math
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.config import load_settings  # noqa: E402

log = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recalculate KPI tables from NAV data.")
    parser.add_argument(
        "--db-path",
        default=None,
        help="SQLite database (default: MFDATA_DB or data/mfdata.db)",
    )
    return parser.parse_args()


def _date_range(
    conn: sqlite3.Connection,
    scheme_code: int,
    as_of: str,
    days: int,
) -> float | None:
    """Return NAV on a specific offset date for a scheme, or None if missing."""
    target = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
    row = conn.execute(
        "SELECT nav FROM nav_history WHERE scheme_code = ? AND date = ? ORDER BY date DESC LIMIT 1",
        (scheme_code, target),
    ).fetchone()
    return row[0] if row else None


def _build_kpi_tables(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Compute all KPI tables from schemes + nav_history.

    Returns a dict mapping table name -> list of row dicts.
    """
    # ---------- load scheme metadata ----------
    schemes = conn.execute(
        """
        SELECT scheme_code, scheme_name, fund_house, scheme_type,
               scheme_category, latest_date, latest_nav
        FROM schemes
        ORDER BY scheme_code
        """
    ).fetchall()

    scheme_kpi_rows: list[dict] = []
    house_map: dict[str, list[dict]] = {}
    cat_map: dict[str, list[dict]] = {}
    type_map: dict[str, list[dict]] = {}

    for row in schemes:
        code = row["scheme_code"]
        nav = row["latest_nav"]
        latest_date = row["latest_date"]
        fund_house = row["fund_house"]
        scheme_type = row["scheme_type"]
        category = row["scheme_category"]

        # placeholder synthetic fields (AMFI data does not publish AUM /
        # expense ratio / dividend yield)
        aum = round(nav * 100, 2) if nav else 0.0
        expense_ratio = 0.5
        dividend_yield = 0.0

        # ---------- scheme-level NAV changes ----------
        nav_change_1d = None
        nav_change_1w = None
        nav_change_1m = None
        if nav and latest_date:
            prev_1d = _date_range(conn, code, latest_date, 1)
            prev_1w = _date_range(conn, code, latest_date, 7)
            prev_1m = _date_range(conn, code, latest_date, 30)
            if prev_1d and prev_1d != 0:
                nav_change_1d = round((nav - prev_1d) / prev_1d * 100, 4)
            if prev_1w and prev_1w != 0:
                nav_change_1w = round((nav - prev_1w) / prev_1w * 100, 4)
            if prev_1m and prev_1m != 0:
                nav_change_1m = round((nav - prev_1m) / prev_1m * 100, 4)

        scheme_kpi_rows.append({
            "scheme_code": code,
            "latest_nav": round(nav, 5) if nav else None,
            "latest_nav_date": latest_date,
            "nav_change_1d": nav_change_1d,
            "nav_change_1w": nav_change_1w,
            "nav_change_1m": nav_change_1m,
            "aum": aum,
            "expense_ratio": expense_ratio,
            "dividend_yield": dividend_yield,
            "trailing_1yr_return": nav_change_1m,
            "sharpe_1yr": None,
            "sortino_1yr": None,
            "max_drawdown": None,
        })

        # bucket for aggregates
        entry = {
            "scheme_code": code,
            "scheme_name": row["scheme_name"],
            "latest_nav": nav,
            "aum": aum,
            "expense_ratio": expense_ratio,
            "nav_change_1d": nav_change_1d,
            "nav_change_1m": nav_change_1m,
        }
        house_map.setdefault(fund_house, []).append(entry)
        cat_map.setdefault(category, []).append(entry)
        type_map.setdefault(scheme_type, []).append(entry)

    # ---------- fund-house aggregates ----------
    fh_kpi_rows: list[dict] = []
    total_aum_all = sum(r["aum"] for r in scheme_kpi_rows) or 1.0
    for house, entries in sorted(house_map.items()):
        if not house:
            continue
        total_aum = sum(e["aum"] for e in entries)
        daily_changes = [e["nav_change_1d"] for e in entries if e["nav_change_1d"] is not None]
        avg_daily_change = round(sum(daily_changes) / len(daily_changes), 4) if daily_changes else None
        stddev_daily_change = None
        if daily_changes:
            mean = sum(daily_changes) / len(daily_changes)
            var = sum((x - mean) ** 2 for x in daily_changes) / len(daily_changes)
            stddev_daily_change = round(math.sqrt(var), 4)
        month_changes = [e["nav_change_1m"] for e in entries if e["nav_change_1m"] is not None]
        best_1m = None
        worst_1m = None
        if month_changes:
            sorted_idx = sorted(
                range(len(month_changes)),
                key=lambda i: month_changes[i],
                reverse=True,
            )
            best_1m = entries[sorted_idx[0]]["scheme_code"] if sorted_idx else None
            worst_1m = entries[sorted_idx[-1]]["scheme_code"] if sorted_idx else None
        avg_expense_ratio = round(sum(e["expense_ratio"] for e in entries) / len(entries), 4)
        market_share = round(total_aum / total_aum_all, 6)
        fh_kpi_rows.append({
            "fund_house": house,
            "total_schemes": len(entries),
            "total_aum": round(total_aum, 2),
            "avg_daily_change": avg_daily_change,
            "stddev_daily_change": stddev_daily_change,
            "best_1m_scheme_code": best_1m,
            "worst_1m_scheme_code": worst_1m,
            "avg_expense_ratio": avg_expense_ratio,
            "market_share": market_share,
        })

    # ---------- category aggregates ----------
    cat_kpi_rows: list[dict] = []
    for cat, entries in sorted(cat_map.items()):
        if not cat:
            continue
        navs = [e["latest_nav"] for e in entries if e["latest_nav"] is not None]
        avg_nav = round(sum(navs) / len(navs), 4) if navs else None
        aums = [e["aum"] for e in entries]
        avg_aum = round(sum(aums) / len(aums), 2)
        daily_changes = [e["nav_change_1d"] for e in entries if e["nav_change_1d"] is not None]
        avg_daily_change = round(sum(daily_changes) / len(daily_changes), 4) if daily_changes else None
        stddev_daily_change = None
        if daily_changes:
            mean = sum(daily_changes) / len(daily_changes)
            var = sum((x - mean) ** 2 for x in daily_changes) / len(daily_changes)
            stddev_daily_change = round(math.sqrt(var), 4)
        avg_expense_ratio = round(sum(e["expense_ratio"] for e in entries) / len(entries), 4)
        top3 = sorted(entries, key=lambda e: e["aum"], reverse=True)[:3]
        top3_by_aum = [{"code": e["scheme_code"], "aum": e["aum"]} for e in top3]
        month_changes = [e["nav_change_1m"] for e in entries if e["nav_change_1m"] is not None]
        cumulative_1yr_return = round(sum(month_changes) / len(month_changes), 4) if month_changes else None
        cat_kpi_rows.append({
            "category": cat,
            "scheme_cnt": len(entries),
            "avg_nav": avg_nav,
            "avg_daily_change": avg_daily_change,
            "stddev_daily_change": stddev_daily_change,
            "avg_aum": avg_aum,
            "avg_expense_ratio": avg_expense_ratio,
            "top3_by_aum": str(top3_by_aum),  # Store as string for JSON compatibility
            "cumulative_1yr_return": cumulative_1yr_return,
        })

    # ---------- fund-type aggregates ----------
    type_kpi_rows: list[dict] = []
    for ftype, entries in sorted(type_map.items()):
        if not ftype:
            continue
        navs = [e["latest_nav"] for e in entries if e["latest_nav"] is not None]
        avg_nav = round(sum(navs) / len(navs), 4) if navs else None
        aums = [e["aum"] for e in entries]
        avg_aum = round(sum(aums) / len(aums), 2)
        daily_changes = [e["nav_change_1d"] for e in entries if e["nav_change_1d"] is not None]
        avg_daily_change = round(sum(daily_changes) / len(daily_changes), 4) if daily_changes else None
        avg_expense_ratio = round(sum(e["expense_ratio"] for e in entries) / len(entries), 4)
        type_kpi_rows.append({
            "fund_type": ftype,
            "scheme_cnt": len(entries),
            "avg_nav": avg_nav,
            "avg_daily_change": avg_daily_change,
            "avg_aum": avg_aum,
            "avg_expense_ratio": avg_expense_ratio,
        })

    return {
        "scheme_kpis": scheme_kpi_rows,
        "fund_house_kpis": fh_kpi_rows,
        "category_kpis": cat_kpi_rows,
        "type_kpis": type_kpi_rows,
    }


def _write_kpis(conn: sqlite3.Connection, tables: dict[str, list[dict]]) -> None:
    """Replace all KPI tables with newly calculated values."""
    with conn:
        conn.executescript(
            """
            DROP TABLE IF EXISTS scheme_kpis;
            CREATE TABLE scheme_kpis (
                scheme_code   INTEGER PRIMARY KEY,
                latest_nav    REAL,
                latest_nav_date TEXT,
                nav_change_1d REAL,
                nav_change_1w REAL,
                nav_change_1m REAL,
                aum           REAL,
                expense_ratio REAL,
                dividend_yield REAL,
                trailing_1yr_return REAL,
                sharpe_1yr    REAL,
                sortino_1yr   REAL,
                max_drawdown  REAL
            );

            DROP TABLE IF EXISTS fund_house_kpis;
            CREATE TABLE fund_house_kpis (
                fund_house        TEXT PRIMARY KEY,
                total_schemes     INTEGER,
                total_aum         REAL,
                avg_daily_change  REAL,
                stddev_daily_change REAL,
                best_1m_scheme_code INTEGER,
                worst_1m_scheme_code INTEGER,
                avg_expense_ratio REAL,
                market_share      REAL
            );

            DROP TABLE IF EXISTS category_kpis;
            CREATE TABLE category_kpis (
                category            TEXT PRIMARY KEY,
                scheme_cnt          INTEGER,
                avg_nav             REAL,
                avg_daily_change    REAL,
                stddev_daily_change REAL,
                avg_aum             REAL,
                avg_expense_ratio   REAL,
                top3_by_aum         TEXT,
                cumulative_1yr_return REAL
            );

            DROP TABLE IF EXISTS type_kpis;
            CREATE TABLE type_kpis (
                fund_type         TEXT PRIMARY KEY,
                scheme_cnt        INTEGER,
                avg_nav           REAL,
                avg_daily_change  REAL,
                avg_aum           REAL,
                avg_expense_ratio REAL
            );
            """
        )

        # scheme_kpis
        if tables["scheme_kpis"]:
            conn.executemany(
                """
                INSERT INTO scheme_kpis (
                    scheme_code, latest_nav, latest_nav_date,
                    nav_change_1d, nav_change_1w, nav_change_1m,
                    aum, expense_ratio, dividend_yield,
                    trailing_1yr_return, sharpe_1yr, sortino_1yr, max_drawdown
                ) VALUES (:scheme_code, :latest_nav, :latest_nav_date,
                          :nav_change_1d, :nav_change_1w, :nav_change_1m,
                          :aum, :expense_ratio, :dividend_yield,
                          :trailing_1yr_return, :sharpe_1yr, :sortino_1yr, :max_drawdown)
                """,
                tables["scheme_kpis"],
            )

        # fund_house_kpis
        if tables["fund_house_kpis"]:
            conn.executemany(
                """
                INSERT INTO fund_house_kpis (
                    fund_house, total_schemes, total_aum,
                    avg_daily_change, stddev_daily_change,
                    best_1m_scheme_code, worst_1m_scheme_code,
                    avg_expense_ratio, market_share
                ) VALUES (:fund_house, :total_schemes, :total_aum,
                          :avg_daily_change, :stddev_daily_change,
                          :best_1m_scheme_code, :worst_1m_scheme_code,
                          :avg_expense_ratio, :market_share)
                """,
                tables["fund_house_kpis"],
            )

        # category_kpis
        if tables["category_kpis"]:
            conn.executemany(
                """
                INSERT INTO category_kpis (
                    category, scheme_cnt, avg_nav, avg_daily_change,
                    stddev_daily_change, avg_aum, avg_expense_ratio,
                    top3_by_aum, cumulative_1yr_return
                ) VALUES (:category, :scheme_cnt, :avg_nav, :avg_daily_change,
                          :stddev_daily_change, :avg_aum, :avg_expense_ratio,
                          :top3_by_aum, :cumulative_1yr_return)
                """,
                tables["category_kpis"],
            )

        # type_kpis
        if tables["type_kpis"]:
            conn.executemany(
                """
                INSERT INTO type_kpis (
                    fund_type, scheme_cnt, avg_nav, avg_daily_change,
                    avg_aum, avg_expense_ratio
                ) VALUES (:fund_type, :scheme_cnt, :avg_nav,
                          :avg_daily_change, :avg_aum, :avg_expense_ratio)
                """,
                tables["type_kpis"],
            )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args()
    db_path = Path(args.db_path) if args.db_path else load_settings().db_path
    if not db_path.exists():
        log.error("Database not found: %s", db_path)
        raise SystemExit(1)

    log.info("Connecting to database: %s", db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = _build_kpi_tables(conn)
        log.info(
            "Computed KPIs: %d schemes, %d fund houses, %d categories, %d types",
            len(tables["scheme_kpis"]),
            len(tables["fund_house_kpis"]),
            len(tables["category_kpis"]),
            len(tables["type_kpis"]),
        )
        _write_kpis(conn, tables)
        log.info("KPI tables written successfully.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
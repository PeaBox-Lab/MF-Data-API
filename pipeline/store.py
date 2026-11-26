"""SQLite storage for scheme metadata and NAV history."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .amfi import SchemeRecord
from .dates import to_api_date, to_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS schemes (
    scheme_code           INTEGER PRIMARY KEY,
    scheme_name           TEXT NOT NULL DEFAULT '',
    fund_house            TEXT NOT NULL DEFAULT '',
    scheme_type           TEXT NOT NULL DEFAULT '',
    scheme_category       TEXT NOT NULL DEFAULT '',
    isin_growth           TEXT,
    isin_div_reinvestment TEXT,
    latest_date           TEXT,
    latest_nav            REAL,
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nav_history (
    scheme_code INTEGER NOT NULL,
    date        TEXT NOT NULL,
    nav         REAL NOT NULL,
    PRIMARY KEY (scheme_code, date)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_nav_history_date ON nav_history(date);
CREATE INDEX IF NOT EXISTS idx_schemes_name ON schemes(scheme_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_schemes_house ON schemes(fund_house COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_schemes_category ON schemes(scheme_category COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

NAV_UPSERT = """
INSERT INTO nav_history (scheme_code, date, nav) VALUES (?, ?, ?)
ON CONFLICT(scheme_code, date) DO UPDATE SET nav = excluded.nav
"""

SCHEME_UPSERT = """
INSERT INTO schemes (
    scheme_code, scheme_name, fund_house, scheme_type, scheme_category,
    isin_growth, isin_div_reinvestment, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
ON CONFLICT(scheme_code) DO UPDATE SET
    scheme_name = CASE WHEN excluded.scheme_name <> '' THEN excluded.scheme_name
                       ELSE schemes.scheme_name END,
    fund_house = CASE WHEN excluded.fund_house <> '' THEN excluded.fund_house
                      ELSE schemes.fund_house END,
    scheme_type = CASE WHEN excluded.scheme_type <> '' THEN excluded.scheme_type
                       ELSE schemes.scheme_type END,
    scheme_category = CASE WHEN excluded.scheme_category <> '' THEN excluded.scheme_category
                           ELSE schemes.scheme_category END,
    isin_growth = COALESCE(excluded.isin_growth, schemes.isin_growth),
    isin_div_reinvestment = COALESCE(excluded.isin_div_reinvestment,
                                     schemes.isin_div_reinvestment),
    updated_at = datetime('now')
"""

META_COLUMNS = """
    scheme_code, scheme_name, fund_house, scheme_type, scheme_category,
    isin_growth, isin_div_reinvestment, latest_date, latest_nav
"""


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class Store:
    """Thin, synchronous wrapper around the SQLite database."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    # ------------------------------------------------------------------ setup
    @contextmanager
    def connect(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        if readonly:
            uri = f"file:{self.path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=30)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 60000")
        if not readonly:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA temp_store = MEMORY")
        try:
            yield conn
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    # ----------------------------------------------------------------- ingest
    def ingest(
        self,
        records: Iterable[SchemeRecord],
        *,
        batch_size: int = 5000,
        progress: int = 100_000,
        log_fn=None,
    ) -> dict[str, int]:
        """Upsert NAV rows and scheme metadata in batches.

        Duplicate ``(scheme_code, date)`` rows inside the input are collapsed so
        the last observation wins.
        """

        nav_batch: dict[tuple[int, str], tuple[int, str, float]] = {}
        scheme_batch: dict[int, tuple] = {}
        processed = 0
        schemes_seen: set[int] = set()

        def flush(conn: sqlite3.Connection) -> None:
            if nav_batch:
                conn.executemany(NAV_UPSERT, list(nav_batch.values()))
                nav_batch.clear()
            if scheme_batch:
                conn.executemany(SCHEME_UPSERT, list(scheme_batch.values()))
                scheme_batch.clear()

        with self.connect() as conn:
            for record in records:
                iso_date = to_iso(record.nav_date)
                nav_batch[(record.scheme_code, iso_date)] = (
                    record.scheme_code,
                    iso_date,
                    record.nav,
                )
                scheme_batch[record.scheme_code] = (
                    record.scheme_code,
                    record.scheme_name,
                    record.fund_house,
                    record.scheme_type,
                    record.scheme_category,
                    record.isin_growth,
                    record.isin_div_reinvestment,
                )
                schemes_seen.add(record.scheme_code)
                processed += 1

                if len(nav_batch) >= batch_size:
                    flush(conn)
                    if log_fn and processed % progress < batch_size:
                        log_fn(f"  stored {processed:,} NAV rows...")
            flush(conn)
            conn.commit()

        return {"rows": processed, "schemes": len(schemes_seen)}

    def refresh_latest(self) -> None:
        """Recompute the denormalised latest NAV columns."""

        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schemes SET
                    latest_date = (
                        SELECT h.date FROM nav_history h
                        WHERE h.scheme_code = schemes.scheme_code
                        ORDER BY h.date DESC LIMIT 1
                    ),
                    latest_nav = (
                        SELECT h.nav FROM nav_history h
                        WHERE h.scheme_code = schemes.scheme_code
                        ORDER BY h.date DESC LIMIT 1
                    )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------- meta
    def set_meta(self, values: dict[str, str]) -> None:
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(str(key), str(value)) for key, value in values.items()],
            )
            conn.commit()

    def get_meta(self) -> dict[str, str]:
        with self.connect(readonly=True) as conn:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def max_nav_date(self) -> str | None:
        with self.connect(readonly=True) as conn:
            row = conn.execute("SELECT MAX(date) AS value FROM nav_history").fetchone()
        return row["value"] if row and row["value"] else None

    # ------------------------------------------------------------------ reads
    @staticmethod
    def _meta(row: sqlite3.Row) -> dict:
        return {
            "fund_house": row["fund_house"],
            "scheme_type": row["scheme_type"],
            "scheme_category": row["scheme_category"],
            "scheme_code": row["scheme_code"],
            "scheme_name": row["scheme_name"],
            "isin_growth": row["isin_growth"],
            "isin_div_reinvestment": row["isin_div_reinvestment"],
        }

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict:
        return {"schemeCode": row["scheme_code"], "schemeName": row["scheme_name"]}

    def get_scheme(self, scheme_code: int) -> dict | None:
        with self.connect(readonly=True) as conn:
            row = conn.execute(
                f"SELECT {META_COLUMNS} FROM schemes WHERE scheme_code = ?",
                (scheme_code,),
            ).fetchone()
        if row is None:
            return None
        meta = self._meta(row)
        meta["latest_date"] = row["latest_date"]
        meta["latest_nav"] = row["latest_nav"]
        return meta

    def list_schemes(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        q: str | None = None,
        fund_house: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []

        if q:
            pattern = _like_pattern(q)
            clauses.append(
                "(scheme_name LIKE ? ESCAPE '\\' OR CAST(scheme_code AS TEXT) = ?)"
            )
            params.extend([pattern, q.strip()])
        if fund_house:
            clauses.append("fund_house = ? COLLATE NOCASE")
            params.append(fund_house)
        if category:
            clauses.append("scheme_category = ? COLLATE NOCASE")
            params.append(category)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "scheme_name COLLATE NOCASE" if q else "scheme_code"
        sql = f"SELECT scheme_code, scheme_name FROM schemes {where} ORDER BY {order}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            params.append(offset)

        with self.connect(readonly=True) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._summary(row) for row in rows]

    def browse_schemes(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        q: str | None = None,
        fund_house: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """List schemes with metadata and latest NAV for the browse UI."""

        clauses: list[str] = []
        params: list = []

        if q:
            clauses.append(
                "(scheme_name LIKE ? ESCAPE '\\' OR CAST(scheme_code AS TEXT) = ?)"
            )
            params.extend([_like_pattern(q), q.strip()])
        if fund_house:
            clauses.append("fund_house = ? COLLATE NOCASE")
            params.append(fund_house)
        if category:
            clauses.append("scheme_category = ? COLLATE NOCASE")
            params.append(category)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "scheme_name COLLATE NOCASE" if q else "scheme_code"
        sql = (
            "SELECT scheme_code, scheme_name, fund_house, scheme_category, "
            f"latest_date, latest_nav FROM schemes {where} ORDER BY {order}"
        )
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            params.append(offset)

        with self.connect(readonly=True) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "schemeCode": row["scheme_code"],
                "schemeName": row["scheme_name"],
                "fundHouse": row["fund_house"] or "",
                "schemeCategory": row["scheme_category"] or "",
                "nav": (
                    f"{row['latest_nav']:.5f}"
                    if row["latest_nav"] is not None
                    else None
                ),
                "date": to_api_date(row["latest_date"]) if row["latest_date"] else None,
            }
            for row in rows
        ]

    def search_schemes(self, q: str, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        pattern = _like_pattern(q)
        prefix = _like_pattern(q).lstrip("%")  # "abc%" style ranking
        sql = """
            SELECT scheme_code, scheme_name FROM schemes
            WHERE scheme_name LIKE ? ESCAPE '\\' OR CAST(scheme_code AS TEXT) = ?
            ORDER BY
                CASE WHEN scheme_name LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END,
                scheme_name COLLATE NOCASE
        """
        params: list = [pattern, q.strip(), prefix]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            params.append(offset)
        with self.connect(readonly=True) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._summary(row) for row in rows]

    def get_history(
        self,
        scheme_code: int,
        *,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> list[tuple[str, float]]:
        clauses = ["scheme_code = ?"]
        params: list = [scheme_code]
        if start:
            clauses.append("date >= ?")
            params.append(start)
        if end:
            clauses.append("date <= ?")
            params.append(end)
        sql = (
            "SELECT date, nav FROM nav_history WHERE "
            + " AND ".join(clauses)
            + " ORDER BY date DESC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect(readonly=True) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [(row["date"], row["nav"]) for row in rows]

    def latest_for(self, scheme_code: int) -> tuple[str, float] | None:
        with self.connect(readonly=True) as conn:
            row = conn.execute(
                "SELECT date, nav FROM nav_history WHERE scheme_code = ? "
                "ORDER BY date DESC LIMIT 1",
                (scheme_code,),
            ).fetchone()
        return (row["date"], row["nav"]) if row else None

    def latest_all(self, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        sql = f"""
            SELECT {META_COLUMNS} FROM schemes
            WHERE latest_date IS NOT NULL
            ORDER BY scheme_code
        """
        params: list = []
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            params.append(offset)
        with self.connect(readonly=True) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "schemeCode": row["scheme_code"],
                "schemeName": row["scheme_name"],
                "nav": f"{row['latest_nav']:.5f}",
                "date": row["latest_date"],
            }
            for row in rows
        ]

    def nav_on_date(self, iso_date: str, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        sql = """
            SELECT s.scheme_code, s.scheme_name, h.nav
            FROM nav_history h
            JOIN schemes s ON s.scheme_code = h.scheme_code
            WHERE h.date = ?
            ORDER BY s.scheme_code
        """
        params: list = [iso_date]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            params.append(offset)
        with self.connect(readonly=True) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "schemeCode": row["scheme_code"],
                "schemeName": row["scheme_name"],
                "nav": f"{row['nav']:.5f}",
                "date": iso_date,
            }
            for row in rows
        ]

    def counts(self) -> dict:
        with self.connect(readonly=True) as conn:
            row = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM schemes) AS scheme_count,
                    (SELECT COUNT(*) FROM nav_history) AS nav_rows,
                    (SELECT MIN(date) FROM nav_history) AS earliest_date,
                    (SELECT MAX(date) FROM nav_history) AS latest_date,
                    (SELECT COUNT(DISTINCT fund_house) FROM schemes) AS fund_house_count,
                    (SELECT COUNT(DISTINCT scheme_category) FROM schemes) AS category_count
                """
            ).fetchone()
        return dict(row) if row else {}

    def fund_houses(self) -> list[dict]:
        with self.connect(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT fund_house AS fundHouse, COUNT(*) AS schemeCount
                FROM schemes WHERE fund_house <> ''
                GROUP BY fund_house ORDER BY fund_house COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def categories(self) -> list[dict]:
        with self.connect(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT scheme_type AS schemeType, scheme_category AS schemeCategory,
                       COUNT(*) AS schemeCount
                FROM schemes WHERE scheme_category <> ''
                GROUP BY scheme_type, scheme_category
                ORDER BY scheme_type, scheme_category COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def iter_schemes(self) -> Iterator[dict]:
        with self.connect(readonly=True) as conn:
            cursor = conn.execute(
                f"SELECT {META_COLUMNS} FROM schemes ORDER BY scheme_code"
            )
            for row in cursor:
                meta = self._meta(row)
                meta["latest_date"] = row["latest_date"]
                meta["latest_nav"] = row["latest_nav"]
                yield meta

    def iter_histories(self) -> Iterator[tuple[int, list[tuple[str, float]]]]:
        """Yield ``(scheme_code, rows)`` without loading the whole table."""

        with self.connect(readonly=True) as conn:
            cursor = conn.execute(
                "SELECT scheme_code, date, nav FROM nav_history "
                "ORDER BY scheme_code, date DESC"
            )
            current: int | None = None
            rows: list[tuple[str, float]] = []
            for row in cursor:
                code = row["scheme_code"]
                if code != current:
                    if current is not None:
                        yield current, rows
                    current = code
                    rows = []
                rows.append((row["date"], row["nav"]))
            if current is not None:
                yield current, rows

    def db_size_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                total += candidate.stat().st_size
        return total

    def integrity_check(self) -> str:
        with self.connect(readonly=True) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        return row[0] if row else "unknown"

    def latest_nav_date(self) -> str | None:
        with self.connect(readonly=True) as conn:
            row = conn.execute(
                "SELECT MAX(latest_date) AS value FROM schemes"
            ).fetchone()
        return row["value"] if row and row["value"] else None

    def nav_dates(self, limit: int = 30) -> list[str]:
        with self.connect(readonly=True) as conn:
            rows = conn.execute(
                "SELECT DISTINCT date FROM nav_history ORDER BY date DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row["date"] for row in rows]

    def has_data(self) -> bool:
        if not self.path.exists():
            return False
        try:
            with self.connect(readonly=True) as conn:
                row = conn.execute("SELECT COUNT(*) AS n FROM nav_history").fetchone()
            return bool(row and row["n"])
        except sqlite3.Error:
            return False

    def movers(self, *, limit: int = 25) -> list[dict]:
        """Return top ``limit`` schemes with biggest 1-day NAV change.

        Schemes are sorted by absolute change % descending.
        Returns list of dicts with schemeCode, schemeName, fundHouse, nav,
        date, change_pct, change_abs.
        """
        # Use window function to get latest 2 NAVs per scheme from nav_history
        sql = """
            WITH ranked AS (
                SELECT h.scheme_code, h.date, h.nav,
                       ROW_NUMBER() OVER (PARTITION BY h.scheme_code ORDER BY h.date DESC) AS rn
                FROM nav_history h
            )
            SELECT r1.scheme_code, r1.date AS latest_date, r1.nav AS latest_nav,
                   r2.nav AS prev_nav
            FROM ranked r1
            LEFT JOIN ranked r2 ON r2.scheme_code = r1.scheme_code AND r2.rn = 2
            WHERE r1.rn = 1
            ORDER BY (r1.nav - r2.nav) / NULLIF(r2.nav, 0) DESC
            LIMIT ?
        """
        with self.connect(readonly=True) as conn:
            rows = conn.execute(sql, (limit,)).fetchall()

        # Join with schemes for metadata
        codes = [row["scheme_code"] for row in rows]
        if not codes:
            return []
        placeholders = ",".join("?" * len(codes))
        meta_sql = f"SELECT scheme_code, scheme_name, fund_house FROM schemes WHERE scheme_code IN ({placeholders})"
        with self.connect(readonly=True) as conn:
            meta_rows = [dict(r) for r in conn.execute(meta_sql, codes).fetchall()]
        meta_map = {m["scheme_code"]: m for m in meta_rows}

        result = []
        for row in rows:
            code = row["scheme_code"]
            meta = meta_map.get(code, {})
            latest_nav = row["latest_nav"]
            prev_nav = row["prev_nav"]
            if prev_nav is not None and prev_nav != 0:
                change_pct = float(f"{(latest_nav - prev_nav) / prev_nav * 100:.2f}")
                change_abs = float(round(latest_nav - prev_nav, 5))
            else:
                change_pct = None
                change_abs = None
            result.append({
                "schemeCode": code,
                "schemeName": meta.get("scheme_name", ""),
                "fundHouse": meta.get("fund_house", ""),
                "nav": f"{latest_nav:.5f}",
                "date": to_api_date(row["latest_date"]),
                "change_pct": change_pct,
                "change_abs": change_abs,
            })
        return result

    def fund_house_stats(self, fund_house: str) -> dict | None:
        """Return aggregated stats for one fund house (AMC)."""
        with self.connect(readonly=True) as conn:
            # total schemes under this fund house
            row = conn.execute(
                """
                SELECT COUNT(*) AS scheme_count
                FROM schemes WHERE fund_house = ?
                """,
                (fund_house,),
            ).fetchone()
            if row is None or row["scheme_count"] == 0:
                return None
            scheme_count = row["scheme_count"]
            # latest date for schemes under this house
            latest = conn.execute(
                """
                SELECT MAX(s.latest_date) AS latest_date
                FROM schemes s
                JOIN nav_history h ON h.scheme_code = s.scheme_code
                WHERE s.fund_house = ?
                """,
                (fund_house,),
            ).fetchone()
            latest_date = latest["latest_date"] if latest else None
            # categories breakdown
            cats = conn.execute(
                """
                SELECT s.scheme_type, s.scheme_category, COUNT(*) AS schemeCount
                FROM schemes s
                WHERE s.fund_house = ?
                GROUP BY s.scheme_type, s.scheme_category
                ORDER BY s.scheme_type, s.scheme_category COLLATE NOCASE
                """,
                (fund_house,),
            ).fetchall()
            categories = [
                {
                    "schemeType": cat["scheme_type"],
                    "schemeCategory": cat["scheme_category"],
                    "schemeCount": cat["schemeCount"],
                }
                for cat in cats
            ]
        return {
            "fund_house": fund_house,
            "scheme_count": scheme_count,
            "latest_nav_date": to_api_date(latest_date) if latest_date else None,
            "categories": categories,
        }

    def category_stats(self, scheme_type: str | None = None, scheme_category: str | None = None) -> dict:
        """Return aggregated stats for one category (or all, filtered by type/category)."""
        with self.connect(readonly=True) as conn:
            clauses: list[str] = []
            params: list = []
            if scheme_type:
                clauses.append("s.scheme_type = ?")
                params.append(scheme_type)
            if scheme_category:
                clauses.append("s.scheme_category = ?")
                params.append(scheme_category)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

            row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM schemes s
                {where}
                """,
                params,
            ).fetchone()
            total = row["total"] if row else 0

            latest_row = conn.execute(
                f"""
                SELECT MAX(s.latest_date) AS latest_date
                FROM schemes s
                {where}
                JOIN nav_history h ON h.scheme_code = s.scheme_code
                """,
                params,
            ).fetchone()
            latest_date = latest_row["latest_date"] if latest_row else None

            cat_rows = conn.execute(
                f"""
                SELECT s.scheme_type AS schemeType,
                       s.scheme_category AS schemeCategory,
                       COUNT(*) AS schemeCount
                FROM schemes s
                {where}
                GROUP BY s.scheme_type, s.scheme_category
                ORDER BY s.scheme_type, s.scheme_category COLLATE NOCASE
                """,
                params,
            ).fetchall()

            categories = [
                {
                    "schemeType": cat["schemeType"],
                    "schemeCategory": cat["schemeCategory"],
                    "schemeCount": cat["schemeCount"],
                }
                for cat in cat_rows
            ]

            return {
                "scheme_type": scheme_type,
                "scheme_category": scheme_category,
                "total_schemes": total,
                "latest_nav_date": to_api_date(latest_date) if latest_date else None,
                "categories": categories,
            }

    def compare_schemes(self, codes: list[int]) -> list[dict]:
        """Return metadata + latest NAV for the given scheme codes."""
        results = []
        for code in codes:
            meta = self.get_scheme(code)
            if meta is None:
                continue
            row = self.latest_for(code)
            if row is None:
                continue
            results.append({
                "schemeCode": code,
                "schemeName": meta["scheme_name"],
                "fundHouse": meta["fund_house"],
                "latestNav": row[1],
                "latestDate": to_api_date(row[0]),
                "schemeCategory": meta["scheme_category"],
                "navChange_pct": None,  # could be computed if needed
            })
        return results

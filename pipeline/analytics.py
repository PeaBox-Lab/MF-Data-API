"""Daily NAV-movement analytics derived from scheme metadata and NAV history.

The module turns the two raw data sets we actually publish (``schemes`` and
``nav_history``) into pre-computed movement tables:

* ``scheme_daily_returns`` — one row per scheme/date with the change from the
  previous published NAV, plus normalised grouping fields.
* ``group_daily_kpis`` — per-date average / median / min / max / dispersion /
  breadth for themes, categories, fund types, fund houses and the whole market.

Important design choices
------------------------
* NAV is an end-of-day net asset value, not a traded price.  A "daily change"
  is the change between consecutive *published* NAVs.
* Direct/Regular and Growth/IDCW plans of the same fund are collapsed to one
  canonical plan (Direct Growth when available) before grouping.  Otherwise a
  single fund would be counted up to four times.
* AMFI does not publish a sector field.  Themes are inferred from scheme names
  within Sectoral/Thematic categories.  A scheme gets one primary theme.
* A change is only computed when the previous observation is at most
  ``max_gap_days`` calendar days old, so long gaps are not reported as daily
  moves.

Usage:
    python scripts/calc_analytics.py [--db-path data/mfdata.db]
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from statistics import median, pstdev

from .dates import to_api_date, utc_now_iso

LEVELS = ("theme", "category", "type", "fund_house", "all")
DEFAULT_MAX_GAP_DAYS = 4

ANALYTICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheme_daily_returns (
    scheme_code   INTEGER NOT NULL,
    date          TEXT NOT NULL,
    prev_date     TEXT NOT NULL,
    gap_days      INTEGER NOT NULL,
    nav           REAL NOT NULL,
    prev_nav      REAL NOT NULL,
    change_pct    REAL NOT NULL,
    scheme_name   TEXT NOT NULL DEFAULT '',
    scheme_family TEXT NOT NULL DEFAULT '',
    family_code   INTEGER,
    is_canonical  INTEGER NOT NULL DEFAULT 0,
    theme         TEXT,
    category      TEXT NOT NULL DEFAULT '',
    fund_type     TEXT NOT NULL DEFAULT '',
    fund_house    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (scheme_code, date)
);

CREATE TABLE IF NOT EXISTS group_daily_kpis (
    level            TEXT NOT NULL,
    grp              TEXT NOT NULL,
    date             TEXT NOT NULL,
    scheme_count     INTEGER NOT NULL,
    avg_change       REAL,
    median_change    REAL,
    min_change       REAL,
    max_change       REAL,
    stddev_change    REAL,
    up_count         INTEGER NOT NULL,
    down_count       INTEGER NOT NULL,
    flat_count       INTEGER NOT NULL,
    best_scheme_code INTEGER,
    best_scheme_name TEXT,
    worst_scheme_code INTEGER,
    worst_scheme_name TEXT,
    index_value      REAL,
    PRIMARY KEY (level, grp, date)
);

CREATE TABLE IF NOT EXISTS analytics_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_returns_date ON scheme_daily_returns(date);
CREATE INDEX IF NOT EXISTS idx_group_daily ON group_daily_kpis(level, date);
CREATE INDEX IF NOT EXISTS idx_group_name ON group_daily_kpis(level, grp, date);
"""

# --------------------------------------------------------------- normalisation

_PLAN_TOKENS = {
    "direct",
    "direct plan",
    "regular",
    "regular plan",
    "growth",
    "growth option",
    "idcw",
    "idcw option",
    "idcw reinvestment option",
    "dividend",
    "dividend option",
    "dividend reinvestment",
    "payout",
    "cumulative",
    "bonus",
    "reinvestment",
}
_SPLIT_RE = re.compile(r"\s*[-–—,]\s*")
_SPACE_RE = re.compile(r"\s+")


def scheme_family(scheme_name: str) -> str:
    """Return a plan-independent family key for a scheme name.

    ``SBI Technology Opportunities Fund - Regular Plan - Growth`` and
    ``SBI TECHNOLOGY OPPORTUNITIES FUND - DIRECT PLAN - GROWTH`` both map to
    ``sbi technology opportunities fund``.
    """
    text = re.sub(
        r"income distribution cum capital withdrawal(?:\s+option)?",
        "IDCW",
        scheme_name or "",
        flags=re.IGNORECASE,
    )
    parts = [_SPACE_RE.sub(" ", part).strip() for part in _SPLIT_RE.split(text)]
    kept = [
        part
        for part in parts
        if part and part.casefold().replace("  ", " ") not in _PLAN_TOKENS
    ]
    family = _SPACE_RE.sub(" ", " ".join(kept)).strip(" -–—,")
    family = re.sub(r"[\s\-]+(?:idcw|growth|dividend)$", "", family, flags=re.I)
    return family.casefold()


def canonical_rank(scheme_name: str) -> int:
    """Rank plan variants; lower is more canonical (Direct Growth first)."""
    low = (scheme_name or "").casefold()
    direct = "direct" in low
    growth = "growth" in low or "cumulative" in low
    if direct and growth:
        return 0
    if growth:
        return 1
    if direct:
        return 2
    return 3


def normalize_category(raw: str) -> str:
    """Collapse AMFI's legacy category aliases into canonical labels."""
    value = (raw or "").replace("\ufffd", "'")
    value = re.sub(r"\s+", " ", value).strip()
    aliases = (
        ("Equity Schemes - ", "Equity Scheme - "),
        ("Hybrid Schemes - ", "Hybrid Scheme - "),
        ("Income/Debt Oriented Schemes - ", "Debt Scheme - "),
        ("Solution Oriented Schemes ** - ", "Solution Oriented Scheme - "),
        ("Childrens' Fund - Childrens' Fund", "Solution Oriented Scheme - Children's Fund"),
        ("ChildrensFund - Childrens' Fund", "Solution Oriented Scheme - Children's Fund"),
    )
    for old, new in aliases:
        if value.startswith(old):
            value = new + value[len(old) :]
    if "Children" in value and "Children" in value.split(" - ", 1)[-1]:
        return "Solution Oriented Scheme - Children's Fund"
    if value.casefold() == "equity scheme - elss":
        value = "ELSS"
    return value


def normalize_type(raw: str) -> str:
    value = re.sub(r"\s+", " ", (raw or "").replace("\ufffd", "'")).strip()
    if value.endswith(" Schemes"):
        value = value[: -len(" Schemes")]
    return value


# Theme patterns are deliberately conservative: a scheme is tagged only when
# its name explicitly says so.  First match wins (insertion order = priority).
_THEME_DEFINITIONS: tuple[tuple[str, str], ...] = (
    (
        "Information Technology",
        r"(?i:\b(?:information technology|technology|technologies|tech|software|digital)\b)|\bIT\b",
    ),
    (
        "Banking & Financial Services",
        r"(?i:\b(?:bank|banking|finance|financial|financial services|nbfc)\b)",
    ),
    (
        "Pharmaceutical & Healthcare",
        r"(?i:\b(?:pharma|pharmaceutical|healthcare|health|medical|hospital)\b)",
    ),
    (
        "Automobile",
        r"(?i:\b(?:auto|automobile|automotive|car)\b)",
    ),
    (
        "Energy & Power",
        r"(?i:\b(?:energy|power|oil|gas|coal)\b)",
    ),
    (
        "Infrastructure",
        r"(?i:\b(?:infrastructure|infra)\b)",
    ),
    (
        "FMCG & Consumption",
        r"(?i:\b(?:fmcg|consumer|consumption|food|beverage)\b)",
    ),
    (
        "Real Estate",
        r"(?i:\b(?:real estate|reit|housing)\b)",
    ),
    (
        "Gold & Precious Metals",
        r"(?i:\b(?:gold|silver|precious metals?)\b)",
    ),
    (
        "Overseas",
        r"(?i:\b(?:overseas|global|international|usa|us equity)\b)",
    ),
)
THEME_PATTERNS = tuple((name, re.compile(pattern)) for name, pattern in _THEME_DEFINITIONS)


def assign_theme(scheme_name: str) -> str | None:
    """Return a single inferred theme for a scheme name, or ``None``."""
    name = scheme_name or ""
    for theme, pattern in THEME_PATTERNS:
        if pattern.search(name):
            return theme
    return None


# ------------------------------------------------------------------- computing

def _family_representatives(conn: sqlite3.Connection) -> dict[int, int]:
    """Pick one canonical scheme code per normalised fund family."""
    families: dict[str, list[tuple[int, int, str]]] = {}
    for row in conn.execute("SELECT scheme_code, scheme_name FROM schemes ORDER BY scheme_code"):
        code, name = row["scheme_code"], row["scheme_name"]
        families.setdefault(scheme_family(name), []).append(
            (canonical_rank(name), code, name)
        )
    return {
        min(variants)[1]: min(variants)[1]
        for variants in families.values()
    }


def compute_daily_returns(
    conn: sqlite3.Connection, *, max_gap_days: int = DEFAULT_MAX_GAP_DAYS
) -> list[dict]:
    """Build one row per scheme/date with its change from the previous NAV."""
    meta = {
        row["scheme_code"]: row
        for row in conn.execute(
            "SELECT scheme_code, scheme_name, fund_house, scheme_type, scheme_category FROM schemes"
        )
    }
    canonical_codes = _family_representatives(conn)
    rows: list[dict] = []
    previous: dict[int, tuple[str, float]] = {}

    query = """
        SELECT scheme_code, date, nav
        FROM nav_history
        ORDER BY scheme_code, date
    """
    for point in conn.execute(query):
        code = point["scheme_code"]
        day = point["date"]
        nav = point["nav"]
        prev = previous.get(code)
        previous[code] = (day, nav)
        if prev is None or not nav or nav <= 0 or not prev[1] or prev[1] <= 0:
            continue
        gap = (date.fromisoformat(day) - date.fromisoformat(prev[0])).days
        if not 0 < gap <= max_gap_days:
            continue
        info = meta.get(code)
        if info is None:
            continue
        name = info["scheme_name"] or ""
        family = scheme_family(name)
        rows.append(
            {
                "scheme_code": code,
                "date": day,
                "prev_date": prev[0],
                "gap_days": gap,
                "nav": round(nav, 6),
                "prev_nav": round(prev[1], 6),
                "change_pct": round((nav / prev[1] - 1) * 100, 6),
                "scheme_name": name,
                "scheme_family": family,
                "family_code": canonical_codes.get(code),
                "is_canonical": 1 if code in canonical_codes else 0,
                "theme": assign_theme(name),
                "category": normalize_category(info["scheme_category"]),
                "fund_type": normalize_type(info["scheme_type"]),
                "fund_house": info["fund_house"] or "",
            }
        )
    return rows


def _group_key(row: dict, level: str) -> str | None:
    if level == "theme":
        return row["theme"]
    if level == "category":
        return row["category"] or None
    if level == "type":
        return row["fund_type"] or None
    if level == "fund_house":
        return row["fund_house"] or None
    return "All schemes"


def compute_group_daily(rows: list[dict]) -> list[dict]:
    """Aggregate canonical scheme returns into per-date group statistics."""
    buckets: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        if not row["is_canonical"]:
            continue
        for level in LEVELS:
            key = _group_key(row, level)
            if key is None:
                continue
            buckets.setdefault((level, key, row["date"]), []).append(row)

    out: list[dict] = []
    index_levels: dict[tuple[str, str], float] = {}
    for (level, grp, day), items in sorted(buckets.items()):
        changes = [item["change_pct"] for item in items]
        best = max(items, key=lambda item: item["change_pct"])
        worst = min(items, key=lambda item: item["change_pct"])
        avg = sum(changes) / len(changes)
        index_key = (level, grp)
        index_level = index_levels.get(index_key, 100.0) * (1 + avg / 100)
        index_levels[index_key] = index_level
        out.append(
            {
                "level": level,
                "grp": grp,
                "date": day,
                "scheme_count": len(items),
                "avg_change": round(avg, 6),
                "median_change": round(median(changes), 6),
                "min_change": round(min(changes), 6),
                "max_change": round(max(changes), 6),
                "stddev_change": round(pstdev(changes) if len(changes) > 1 else 0.0, 6),
                "up_count": sum(1 for change in changes if change > 0.0001),
                "down_count": sum(1 for change in changes if change < -0.0001),
                "flat_count": sum(1 for change in changes if abs(change) <= 0.0001),
                "best_scheme_code": best["scheme_code"],
                "best_scheme_name": best["scheme_name"],
                "worst_scheme_code": worst["scheme_code"],
                "worst_scheme_name": worst["scheme_name"],
                "index_value": round(index_level, 6),
            }
        )
    return out


# -------------------------------------------------------------------- storage

def write_analytics(
    conn: sqlite3.Connection,
    rows: list[dict],
    group_rows: list[dict],
    *,
    max_gap_days: int = DEFAULT_MAX_GAP_DAYS,
) -> None:
    """Replace the analytics tables with newly computed values."""
    generated_at = utc_now_iso()
    with conn:
        conn.execute("DROP TABLE IF EXISTS scheme_daily_returns")
        conn.execute("DROP TABLE IF EXISTS group_daily_kpis")
        conn.execute("DROP TABLE IF EXISTS analytics_meta")
        conn.executescript(ANALYTICS_SCHEMA)
        if rows:
            conn.executemany(
                """
                INSERT INTO scheme_daily_returns (
                    scheme_code, date, prev_date, gap_days, nav, prev_nav,
                    change_pct, scheme_name, scheme_family, family_code,
                    is_canonical, theme, category, fund_type, fund_house
                ) VALUES (
                    :scheme_code, :date, :prev_date, :gap_days, :nav, :prev_nav,
                    :change_pct, :scheme_name, :scheme_family, :family_code,
                    :is_canonical, :theme, :category, :fund_type, :fund_house
                )
                """,
                rows,
            )
        if group_rows:
            conn.executemany(
                """
                INSERT INTO group_daily_kpis (
                    level, grp, date, scheme_count, avg_change, median_change,
                    min_change, max_change, stddev_change, up_count, down_count,
                    flat_count, best_scheme_code, best_scheme_name,
                    worst_scheme_code, worst_scheme_name, index_value
                ) VALUES (
                    :level, :grp, :date, :scheme_count, :avg_change, :median_change,
                    :min_change, :max_change, :stddev_change, :up_count, :down_count,
                    :flat_count, :best_scheme_code, :best_scheme_name,
                    :worst_scheme_code, :worst_scheme_name, :index_value
                )
                """,
                group_rows,
            )
        conn.executemany(
            "INSERT INTO analytics_meta (key, value) VALUES (?, ?)",
            [
                ("generated_at", generated_at),
                ("max_gap_days", str(max_gap_days)),
                ("scheme_return_rows", str(len(rows))),
                ("group_daily_rows", str(len(group_rows))),
                (
                    "notes",
                    "NAV is an end-of-day net asset value, not a traded price. "
                    "Themes are inferred from scheme names; AMFI publishes no sector field.",
                ),
            ],
        )


def has_analytics(conn: sqlite3.Connection) -> bool:
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    return {"scheme_daily_returns", "group_daily_kpis", "analytics_meta"} <= names


# --------------------------------------------------------------------- queries

_RETURN_COLUMNS = (
    "date",
    "scheme_count",
    "avg_change",
    "median_change",
    "min_change",
    "max_change",
    "stddev_change",
    "up_count",
    "down_count",
    "flat_count",
    "best_scheme_code",
    "best_scheme_name",
    "worst_scheme_code",
    "worst_scheme_name",
    "index_value",
)


def _meta_map(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM analytics_meta")}


def _public_row(row: sqlite3.Row) -> dict:
    payload = {key: row[key] for key in _RETURN_COLUMNS}
    payload["date"] = to_api_date(payload["date"])
    return payload


def summary_payload(conn: sqlite3.Connection) -> dict:
    """Overview of the pre-computed analytics dataset."""
    meta = _meta_map(conn)
    dates = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT date FROM group_daily_kpis ORDER BY date"
        )
    ]
    counts = {
        row["level"]: row["n"]
        for row in conn.execute(
            "SELECT level, COUNT(DISTINCT grp) AS n FROM group_daily_kpis GROUP BY level"
        )
    }
    scheme_rows = conn.execute(
        "SELECT COUNT(DISTINCT scheme_code) FROM scheme_daily_returns"
    ).fetchone()[0]
    families = conn.execute(
        "SELECT COUNT(DISTINCT scheme_family) FROM scheme_daily_returns"
    ).fetchone()[0]
    return {
        "generatedAt": meta.get("generated_at"),
        "earliestDate": to_api_date(dates[0]) if dates else None,
        "latestDate": to_api_date(dates[-1]) if dates else None,
        "dateCount": len(dates),
        "schemeCount": scheme_rows,
        "familyCount": families,
        "groups": {level: counts.get(level, 0) for level in LEVELS},
        "maxGapDays": int(meta.get("max_gap_days") or DEFAULT_MAX_GAP_DAYS),
        "notes": meta.get("notes", ""),
    }


def groups_payload(conn: sqlite3.Connection, level: str) -> list[dict]:
    """List available group names for a level, with coverage counts."""
    if level not in LEVELS:
        raise ValueError(f"Unknown analytics level: {level}")
    return [
        {
            "name": row["grp"],
            "days": row["days"],
            "schemeCount": row["schemes"],
            "latestDate": to_api_date(row["latest"]),
        }
        for row in conn.execute(
            """
            SELECT grp,
                   COUNT(*) AS days,
                   MAX(scheme_count) AS schemes,
                   MAX(date) AS latest
            FROM group_daily_kpis
            WHERE level = ?
            GROUP BY grp
            ORDER BY grp
            """,
            (level,),
        )
    ]


def all_movement_payload(
    conn: sqlite3.Connection, *, start: str | None = None
) -> list[dict]:
    """Return every group/date row (used by the static JSON export)."""
    clause = "WHERE date >= ?" if start else ""
    params = (start,) if start else ()
    rows = conn.execute(
        f"""
        SELECT * FROM group_daily_kpis
        {clause}
        ORDER BY level, grp, date
        """,
        params,
    ).fetchall()
    return [
        {"level": row["level"], "group": row["grp"], **_public_row(row)}
        for row in rows
    ]


def movement_payload(
    conn: sqlite3.Connection,
    level: str,
    group: str | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
    limit: int = 100,
    min_schemes: int = 3,
) -> dict:
    """Return a group's time series plus a ranking of each group's latest day."""
    if level not in LEVELS:
        raise ValueError(f"Unknown analytics level: {level}")
    latest = conn.execute(
        "SELECT MAX(date) FROM group_daily_kpis WHERE level = ?", (level,)
    ).fetchone()[0]
    ranking: list[dict] = []
    if latest:
        rows = conn.execute(
            """
            SELECT g.* FROM group_daily_kpis g
            JOIN (
                SELECT grp, MAX(date) AS d
                FROM group_daily_kpis
                WHERE level = ?
                GROUP BY grp
            ) latest ON latest.grp = g.grp AND latest.d = g.date
            WHERE g.level = ? AND g.scheme_count >= ?
            ORDER BY g.avg_change DESC, g.grp
            LIMIT ?
            """,
            (level, level, max(1, min_schemes), limit),
        ).fetchall()
        ranking = [_public_row(row) for row in rows]

    series: list[dict] = []
    if group is not None:
        clauses = ["level = ?", "grp = ?"]
        params: list = [level, group]
        if start:
            clauses.append("date >= ?")
            params.append(start)
        if end:
            clauses.append("date <= ?")
            params.append(end)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT * FROM group_daily_kpis
            WHERE {' AND '.join(clauses)}
            ORDER BY date DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        series = [_public_row(row) for row in reversed(rows)]

    meta = _meta_map(conn)
    return {
        "level": level,
        "group": group,
        "generatedAt": meta.get("generated_at"),
        "latestDate": to_api_date(latest) if latest else None,
        "count": len(series or ranking),
        "data": series if group is not None else ranking,
        "ranking": ranking,
        "notes": meta.get("notes", ""),
    }

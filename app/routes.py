"""Public API routes (mounted at /api/v1 and, for compatibility, at /)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from pipeline.analytics import (
    groups_payload,
    has_analytics,
    movement_payload,
    summary_payload,
)
from pipeline.dates import parse_flexible_date, to_api_date, to_iso
from pipeline.export_static import DATA_SOURCES
from pipeline.store import Store

from .deps import ApiError, get_store
from .schemas import (
    Category,
    CategoryStatsResponse,
    CompareResponse,
    DataSourcesResponse,
    FundHouse,
    FundHouseStats,
    Health,
    LatestNav,
    MoverItem,
    MoverResponse,
    NavOnDate,
    SchemeBrowse,
    SchemeHistory,
    SchemeMeta,
    SchemeSummary,
    Stats,
)

router = APIRouter()

StoreDep = Annotated[Store, Depends(get_store)]


def _ensure_data(store: Store) -> None:
    if not store.has_data():
        raise ApiError(
            503,
            "NAV database is not available yet. Run the data pipeline first "
            "(python -m pipeline sync).",
            "UNAVAILABLE",
        )


@contextmanager
def _analytics_connection(store: Store) -> Iterator:
    """Open a read-only connection, failing clearly if analytics are missing."""
    with store.connect(readonly=True) as conn:
        if not has_analytics(conn):
            raise ApiError(
                503,
                "Analytics tables are not available yet. Run "
                "'python scripts/calc_analytics.py' first.",
                "UNAVAILABLE",
            )
        yield conn


def _kpi_row(store: Store, table: str, column: str, value: object) -> dict:
    if table not in {
        "scheme_kpis",
        "fund_house_kpis",
        "category_kpis",
        "type_kpis",
    }:
        raise ValueError(f"Unknown KPI table: {table}")
    with store.connect(readonly=True) as conn:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if table not in names:
            raise ApiError(
                503,
                f"KPI table {table} is not available. Run 'python scripts/calc_kpis.py'.",
                "UNAVAILABLE",
            )
        row = conn.execute(
            f"SELECT * FROM {table} WHERE {column} = ?", (value,)
        ).fetchone()
        if row is None:
            raise ApiError(404, f"KPI {value!r} not found in {table}", "NOT_FOUND")
        cols = [column[1] for column in conn.execute(f"PRAGMA table_info({table})")]
        return dict(zip(cols, row, strict=False))


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


def _date_range(start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
    try:
        start = parse_flexible_date(start_date) if start_date else None
        end = parse_flexible_date(end_date) if end_date else None
    except ValueError as exc:
        raise ApiError(400, str(exc), "BAD_REQUEST") from exc
    if start and end and start > end:
        raise ApiError(400, "startDate must be on or before endDate", "BAD_REQUEST")
    return (to_iso(start) if start else None, to_iso(end) if end else None)


def _history(store: Store, scheme_code: int, start: str | None, end: str | None) -> dict:
    _ensure_data(store)
    meta = store.get_scheme(scheme_code)
    if meta is None:
        raise ApiError(404, f"Scheme {scheme_code} not found", "NOT_FOUND")
    rows = store.get_history(scheme_code, start=start, end=end)
    return {
        "meta": _meta_payload(meta),
        "data": [{"date": to_api_date(day), "nav": f"{nav:.5f}"} for day, nav in rows],
        "status": "SUCCESS",
    }


# --------------------------------------------------------------------- scheme
@router.get(
    "/mf",
    response_model=list[SchemeSummary],
    summary="List mutual fund schemes",
    description=(
        "Returns the scheme master list. Without `limit`, every scheme is returned "
        "(about 14,000 rows). Use `q`, `fund_house` or `category` to filter, and "
        "`limit`/`offset` to paginate."
    ),
    tags=["Schemes"],
)
def list_schemes(
    store: StoreDep,
    limit: Annotated[int | None, Query(ge=1, le=50000, description="Page size")] = None,
    offset: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
    q: Annotated[str | None, Query(min_length=1, max_length=100, description="Name filter")] = None,
    fund_house: Annotated[str | None, Query(description="Exact fund house name")] = None,
    category: Annotated[str | None, Query(description="Exact scheme category")] = None,
):
    _ensure_data(store)
    return store.list_schemes(
        limit=limit, offset=offset, q=q, fund_house=fund_house, category=category
    )


@router.get(
    "/mf/browse",
    response_model=list[SchemeBrowse],
    summary="Browse schemes with metadata and latest NAV",
    description=(
        "Returns the scheme master list enriched with fund house, category and the "
        "latest published NAV. Supports the same filters and pagination as `/mf`."
    ),
    tags=["Schemes"],
)
def browse_schemes(
    store: StoreDep,
    limit: Annotated[int | None, Query(ge=1, le=50000, description="Page size")] = None,
    offset: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
    q: Annotated[str | None, Query(min_length=1, max_length=100, description="Name filter")] = None,
    fund_house: Annotated[str | None, Query(description="Exact fund house name")] = None,
    category: Annotated[str | None, Query(description="Exact scheme category")] = None,
):
    _ensure_data(store)
    return store.browse_schemes(
        limit=limit, offset=offset, q=q, fund_house=fund_house, category=category
    )


@router.get(
    "/mf/search",
    response_model=list[SchemeSummary],
    summary="Search schemes by name or code",
    description=(
        "Case-insensitive search across scheme names. Exact scheme code matches are "
        "also returned. Prefix matches are ranked first."
    ),
    tags=["Schemes"],
)
def search_schemes(
    store: StoreDep,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Search text")],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    _ensure_data(store)
    return store.search_schemes(q, limit=limit, offset=offset)


@router.get(
    "/mf/latest",
    response_model=list[LatestNav],
    summary="Latest NAV for every scheme",
    description=(
        "Returns the most recent stored NAV for each scheme. Without `limit` this "
        "returns roughly 14,000 rows; paginate for lighter responses."
    ),
    tags=["NAV"],
)
def latest_all(
    store: StoreDep,
    limit: Annotated[int | None, Query(ge=1, le=50000)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    _ensure_data(store)
    rows = store.latest_all(limit=limit, offset=offset)
    return [
        {
            "schemeCode": row["schemeCode"],
            "schemeName": row["schemeName"],
            "nav": row["nav"],
            "date": to_api_date(row["date"]),
        }
        for row in rows
    ]


@router.get(
    "/mf/{scheme_code}",
    response_model=SchemeHistory,
    summary="Full NAV history for a scheme",
    description=(
        "Returns scheme metadata and NAV observations in reverse chronological "
        "order. Filter with `startDate` and `endDate` (YYYY-MM-DD or DD-MM-YYYY)."
    ),
    responses={
        404: {"model": dict, "description": "Scheme not found"},
        400: {"model": dict, "description": "Invalid date range"},
    },
    tags=["NAV"],
)
def scheme_history(
    store: StoreDep,
    scheme_code: Annotated[int, Path(ge=1, description="AMFI scheme code")],
    startDate: Annotated[str | None, Query(description="Inclusive start date")] = None,
    endDate: Annotated[str | None, Query(description="Inclusive end date")] = None,
):
    start, end = _date_range(startDate, endDate)
    return _history(store, scheme_code, start, end)


@router.get(
    "/mf/{scheme_code}/latest",
    response_model=SchemeHistory,
    summary="Latest NAV for a scheme",
    description="Returns metadata plus the single most recent NAV observation.",
    responses={404: {"model": dict, "description": "Scheme not found"}},
    tags=["NAV"],
)
def scheme_latest(
    store: StoreDep,
    scheme_code: Annotated[int, Path(ge=1, description="AMFI scheme code")],
):
    _ensure_data(store)
    meta = store.get_scheme(scheme_code)
    if meta is None:
        raise ApiError(404, f"Scheme {scheme_code} not found", "NOT_FOUND")
    row = store.latest_for(scheme_code)
    if row is None:
        raise ApiError(404, f"No NAV data for scheme {scheme_code}", "NOT_FOUND")
    return {
        "meta": _meta_payload(meta),
        "data": [{"date": to_api_date(row[0]), "nav": f"{row[1]:.5f}"}],
        "status": "SUCCESS",
    }


@router.get(
    "/mf/{scheme_code}/meta",
    response_model=SchemeMeta,
    summary="Scheme metadata only",
    responses={404: {"model": dict, "description": "Scheme not found"}},
    tags=["Schemes"],
)
def scheme_meta(
    store: StoreDep,
    scheme_code: Annotated[int, Path(ge=1, description="AMFI scheme code")],
):
    _ensure_data(store)
    meta = store.get_scheme(scheme_code)
    if meta is None:
        raise ApiError(404, f"Scheme {scheme_code} not found", "NOT_FOUND")
    return _meta_payload(meta)


# ------------------------------------------------------------------ reference
@router.get(
    "/fund-houses",
    response_model=list[FundHouse],
    summary="List fund houses with scheme counts",
    tags=["Reference"],
)
def fund_houses(store: StoreDep):
    _ensure_data(store)
    return store.fund_houses()


@router.get(
    "/fund-houses/{fund_house}/schemes",
    response_model=list[SchemeSummary],
    summary="List schemes for a fund house",
    responses={404: {"model": dict, "description": "Fund house not found"}},
    tags=["Reference"],
)
def fund_house_schemes(store: StoreDep, fund_house: str):
    _ensure_data(store)
    schemes = store.list_schemes(fund_house=fund_house)
    if not schemes:
        raise ApiError(404, f"Fund house {fund_house!r} not found", "NOT_FOUND")
    return schemes


@router.get(
    "/categories",
    response_model=list[Category],
    summary="List scheme categories with counts",
    tags=["Reference"],
)
def categories(store: StoreDep):
    _ensure_data(store)
    return store.categories()


@router.get(
    "/categories/stats",
    response_model=CategoryStatsResponse,
    summary="Category stats with counts and latest NAV date",
    tags=["Reference"],
)
def category_stats(
    store: StoreDep,
    scheme_type: Annotated[str | None, Query(description="Scheme type filter, e.g. Open Ended Schemes")] = None,
    scheme_category: Annotated[str | None, Query(description="Scheme category filter, e.g. Equity Scheme")] = None,
):
    _ensure_data(store)
    return store.category_stats(scheme_type=scheme_type, scheme_category=scheme_category)


@router.get(
    "/nav/{date}",
    response_model=NavOnDate,
    summary="All NAVs published on a date",
    description="Returns NAVs for every scheme on the requested date (YYYY-MM-DD or DD-MM-YYYY).",
    tags=["NAV"],
)
def nav_on_date(
    store: StoreDep,
    date: Annotated[str, Path(description="NAV date")],
    limit: Annotated[int, Query(ge=1, le=5000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    _ensure_data(store)
    try:
        parsed = parse_flexible_date(date)
    except ValueError as exc:
        raise ApiError(400, str(exc), "BAD_REQUEST") from exc
    iso = to_iso(parsed)
    rows = store.nav_on_date(iso, limit=limit, offset=offset)
    return {
        "date": to_api_date(iso),
        "data": [
            {
                "schemeCode": row["schemeCode"],
                "schemeName": row["schemeName"],
                "nav": row["nav"],
                "date": to_api_date(iso),
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------- meta
@router.get(
    "/dates",
    response_model=list[str],
    summary="Recent NAV dates",
    description="Returns the most recent dates for which NAV rows exist, newest first.",
    tags=["Meta"],
)
def recent_dates(
    store: StoreDep,
    limit: Annotated[int, Query(ge=1, le=365)] = 30,
):
    _ensure_data(store)
    return [to_api_date(day) for day in store.nav_dates(limit)]


@router.get("/stats", response_model=Stats, summary="Dataset statistics", tags=["Meta"])
def stats(store: StoreDep):
    _ensure_data(store)
    counts = store.counts()
    meta = store.get_meta()
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "latest_nav_date": to_api_date(counts["latest_date"]) if counts.get("latest_date") else None,
        "earliest_nav_date": to_api_date(counts["earliest_date"]) if counts.get("earliest_date") else None,
        "scheme_count": counts.get("scheme_count", 0),
        "nav_rows": counts.get("nav_rows", 0),
        "fund_house_count": counts.get("fund_house_count", 0),
        "category_count": counts.get("category_count", 0),
        "source": meta.get("source", "AMFI India"),
        "source_url": meta.get(
            "source_url", "https://www.amfiindia.com/net-asset-value/nav-download"
        ),
        "database_bytes": store.db_size_bytes(),
    }


@router.get("/health", response_model=Health, summary="Health check", tags=["Meta"])
def health(store: StoreDep):
    if not store.has_data():
        raise ApiError(503, "NAV database is not available", "UNAVAILABLE")
    counts = store.counts()
    meta = store.get_meta()
    return {
        "status": "ok",
        "database": "ok",
        "latest_nav_date": to_api_date(counts["latest_date"]) if counts.get("latest_date") else None,
        "last_sync": meta.get("last_sync"),
        "scheme_count": counts.get("scheme_count", 0),
    }


@router.get("/movers/latest", response_model=MoverResponse, summary="Top NAV movers", tags=["NAV"])
def movers_latest(
    store: StoreDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    direction: Annotated[Literal["gainers", "losers"], Query(description="Sort direction")] = "gainers",
):
    _ensure_data(store)
    movers = store.movers(limit=limit)
    # direction=gainers => sort descending change_pct; direction=losers => ascending
    reverse = direction == "gainers"
    sorted_movers = sorted(
        [m for m in movers if m["change_pct"] is not None],
        key=lambda x: x["change_pct"] if x["change_pct"] is not None else -float("inf"),
        reverse=reverse,
    )
    return {"data": sorted_movers, "count": len(sorted_movers)}


@router.get("/movers/search", response_model=list[MoverItem], summary="Search movers by fund house", tags=["NAV"])
def movers_search(
    store: StoreDep,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Fund house name filter")],
):
    _ensure_data(store)
    movers = store.movers(limit=200)
    filtered = [
        m for m in movers
        if q.lower() in m.get("fundHouse", "").lower()
    ]
    return filtered


@router.get("/fund-houses/{fund_house}/stats", response_model=FundHouseStats, summary="Fund house stats", tags=["Reference"])
def fund_house_stats(
    store: StoreDep,
    fund_house: Annotated[str, Path(description="Fund house / AMC name")],
):
    _ensure_data(store)
    stats = store.fund_house_stats(fund_house)
    if stats is None:
        raise ApiError(404, f"Fund house {fund_house!r} not found", "NOT_FOUND")
    return stats


@router.get("/compare", response_model=CompareResponse, summary="Compare multiple schemes", tags=["NAV"])
def compare(
    store: StoreDep,
    codes: Annotated[str, Query(description="Comma-separated AMFI scheme codes, e.g. 125497,100119")],
):
    _ensure_data(store)
    code_list = [int(c.strip()) for c in codes.split(",") if c.strip()]
    if not code_list:
        raise ApiError(400, "At least one scheme code required", "BAD_REQUEST")
    return {"data": store.compare_schemes(code_list)}


@router.get("/data-sources", response_model=DataSourcesResponse, summary="Free mutual fund data API directory", tags=["Meta"])
def data_sources():
    """Return the curated directory of free mutual fund data APIs worldwide."""
    return {"data": DATA_SOURCES}


# ============================================================
# Analytics Endpoints
# ============================================================

AnalyticsLevel = Annotated[
    Literal["theme", "category", "type", "fund_house", "all"],
    Query(description="Grouping level for the movement data"),
]


@router.get(
    "/analytics/summary",
    response_model=dict,
    summary="Analytics dataset overview",
    tags=["Analytics"],
)
def analytics_summary(store: StoreDep):
    """Return coverage, freshness and methodology notes for analytics tables."""
    with _analytics_connection(store) as conn:
        return summary_payload(conn)


@router.get(
    "/analytics/groups",
    response_model=list[dict],
    summary="Available analytics groups",
    tags=["Analytics"],
)
def analytics_groups(store: StoreDep, level: AnalyticsLevel = "theme"):
    """List the groups available at a level (themes, categories, AMCs, ...)."""
    with _analytics_connection(store) as conn:
        return groups_payload(conn, level)


@router.get(
    "/analytics/movement",
    response_model=dict,
    summary="Daily NAV movement by theme, category, type or fund house",
    description=(
        "Average, median, min and max daily NAV change, dispersion and breadth "
        "for a group across dates. Without `group`, returns the latest-day "
        "ranking of all groups at the chosen level. Direct/Regular and "
        "Growth/IDCW plan variants are collapsed to one canonical plan."
    ),
    tags=["Analytics"],
)
def analytics_movement(
    store: StoreDep,
    level: AnalyticsLevel = "theme",
    group: Annotated[
        str | None,
        Query(max_length=200, description="Group name; omit for a latest-day ranking"),
    ] = None,
    startDate: Annotated[str | None, Query(description="Inclusive start date")] = None,
    endDate: Annotated[str | None, Query(description="Inclusive end date")] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 100,
    minSchemes: Annotated[
        int, Query(ge=1, le=10000, description="Minimum schemes in a ranked group")
    ] = 3,
):
    start, end = _date_range(startDate, endDate)
    with _analytics_connection(store) as conn:
        try:
            return movement_payload(
                conn,
                level,
                group,
                start=start,
                end=end,
                limit=limit,
                min_schemes=minSchemes,
            )
        except ValueError as exc:
            raise ApiError(400, str(exc), "BAD_REQUEST") from exc


# ============================================================
# KPI Endpoints
# ============================================================

@router.get(
    "/kpi/scheme/{code}",
    response_model=dict,
    summary="Scheme-level KPIs",
    tags=["KPI"],
)
def scheme_kpi(code: int, store: StoreDep):
    """Return KPIs for a specific scheme."""
    return _kpi_row(store, "scheme_kpis", "scheme_code", code)


@router.get(
    "/kpi/fund-house/{name}",
    response_model=dict,
    summary="Fund-house-level KPIs",
    tags=["KPI"],
)
def fund_house_kpi(name: str, store: StoreDep):
    """Return KPIs for a specific fund house."""
    return _kpi_row(store, "fund_house_kpis", "fund_house", name)


@router.get(
    "/kpi/category/{cat}",
    response_model=dict,
    summary="Category-level KPIs",
    tags=["KPI"],
)
def category_kpi(cat: str, store: StoreDep):
    """Return KPIs for a specific category."""
    return _kpi_row(store, "category_kpis", "category", cat)


@router.get(
    "/kpi/type/{ftype}",
    response_model=dict,
    summary="Fund-type-level KPIs (equity/debt/hybrid)",
    tags=["KPI"],
)
def type_kpi(ftype: str, store: StoreDep):
    """Return KPIs for a fund type."""
    return _kpi_row(store, "type_kpis", "fund_type", ftype)

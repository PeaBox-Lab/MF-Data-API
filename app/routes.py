"""Public API routes (mounted at /api/v1 and, for compatibility, at /)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from pipeline.dates import parse_flexible_date, to_api_date, to_iso
from pipeline.store import Store

from .deps import ApiError, get_store
from .schemas import (
    Category,
    FundHouse,
    Health,
    LatestNav,
    NavOnDate,
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

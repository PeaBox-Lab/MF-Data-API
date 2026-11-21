"""Pydantic response schemas (also used to build the OpenAPI docs)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SchemeSummary(BaseModel):
    schemeCode: int = Field(..., examples=[125497])
    schemeName: str = Field(..., examples=["SBI Small Cap Fund - Direct Plan - Growth"])


class NavPoint(BaseModel):
    date: str = Field(..., examples=["20-11-2026"], description="NAV date (DD-MM-YYYY)")
    nav: str = Field(..., examples=["210.02130"], description="NAV as a fixed-point string")


class SchemeMeta(BaseModel):
    fund_house: str = Field(..., examples=["SBI Mutual Fund"])
    scheme_type: str = Field(..., examples=["Open Ended Schemes"])
    scheme_category: str = Field(..., examples=["Equity Scheme - Small Cap Fund"])
    scheme_code: int = Field(..., examples=[125497])
    scheme_name: str = Field(..., examples=["SBI Small Cap Fund - Direct Plan - Growth"])
    isin_growth: str | None = Field(None, examples=["INF200K01T51"])
    isin_div_reinvestment: str | None = None


class SchemeHistory(BaseModel):
    meta: SchemeMeta
    data: list[NavPoint]
    status: str = Field("SUCCESS", examples=["SUCCESS"])


class LatestNav(SchemeSummary):
    nav: str = Field(..., examples=["210.02130"])
    date: str = Field(..., examples=["20-11-2026"])


class FundHouse(BaseModel):
    fundHouse: str = Field(..., examples=["SBI Mutual Fund"])
    schemeCount: int = Field(..., examples=[420])


class Category(BaseModel):
    schemeType: str = Field(..., examples=["Open Ended Schemes"])
    schemeCategory: str = Field(..., examples=["Equity Scheme - Small Cap Fund"])
    schemeCount: int = Field(..., examples=[42])


class NavOnDate(BaseModel):
    date: str = Field(..., examples=["20-11-2026"])
    data: list[LatestNav]


class Stats(BaseModel):
    generated_at: str
    latest_nav_date: str | None
    earliest_nav_date: str | None
    scheme_count: int
    nav_rows: int
    fund_house_count: int
    category_count: int
    source: str = "AMFI India"
    source_url: str = "https://www.amfiindia.com/net-asset-value/nav-download"
    database_bytes: int


class Health(BaseModel):
    status: str = Field(..., examples=["ok"])
    database: str = Field(..., examples=["ok"])
    latest_nav_date: str | None = None
    last_sync: str | None = None
    scheme_count: int = 0


class ErrorResponse(BaseModel):
    status: str = Field(..., examples=["NOT_FOUND"])
    message: str = Field(..., examples=["Scheme 999999 not found"])

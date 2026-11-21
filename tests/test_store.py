from __future__ import annotations

from datetime import date

import pytest

from pipeline.amfi import SchemeRecord, parse_history, parse_navall
from pipeline.store import Store


@pytest.fixture()
def store(tmp_path, fixture) -> Store:
    store = Store(tmp_path / "mfdata.db")
    store.init_schema()
    store.ingest(parse_navall(fixture("navall_sample.txt")))
    store.ingest(parse_history(fixture("navhistory_sample.txt")))
    store.refresh_latest()
    return store


def test_counts_and_metadata(store: Store):
    counts = store.counts()
    assert counts["scheme_count"] == 4
    assert counts["nav_rows"] == 6
    assert counts["latest_date"] == "2026-11-20"
    assert counts["fund_house_count"] == 3

    meta = store.get_scheme(125497)
    assert meta is not None
    assert meta["scheme_name"] == "SBI Small Cap Fund - Direct Plan - Growth"
    assert meta["fund_house"] == "SBI Mutual Fund"
    assert meta["isin_growth"] == "INF200K01T51"
    assert meta["latest_date"] == "2026-11-20"


def test_history_order_and_filters(store: Store):
    rows = store.get_history(125497)
    assert [row[0] for row in rows] == ["2026-11-20", "2026-11-17", "2026-11-16"]
    assert rows[0][1] == pytest.approx(210.0213)

    filtered = store.get_history(125497, start="2026-11-17", end="2026-11-18")
    assert [row[0] for row in filtered] == ["2026-11-17"]

    assert store.latest_for(125497)[0] == "2026-11-20"
    assert store.latest_for(999999) is None


def test_list_and_search(store: Store):
    all_schemes = store.list_schemes()
    assert [row["schemeCode"] for row in all_schemes] == [100121, 125497, 135762, 135765]

    paged = store.list_schemes(limit=2, offset=2)
    assert [row["schemeCode"] for row in paged] == [135762, 135765]

    axis = store.search_schemes("axis")
    assert [row["schemeCode"] for row in axis] == [135762, 135765]

    by_code = store.search_schemes("125497")
    assert [row["schemeCode"] for row in by_code] == [125497]

    by_house = store.list_schemes(fund_house="SBI Mutual Fund")
    assert [row["schemeCode"] for row in by_house] == [125497]

    by_category = store.list_schemes(category="ELSS")
    assert [row["schemeCode"] for row in by_category] == [100121]


def test_latest_and_by_date(store: Store):
    latest = store.latest_all()
    assert len(latest) == 4
    assert latest[0]["date"] == "2026-11-20"

    on_date = store.nav_on_date("2026-11-20")
    assert len(on_date) == 4
    assert {row["schemeCode"] for row in on_date} == {100121, 125497, 135762, 135765}


def test_upsert_updates_nav(store: Store):
    store.ingest(
        [
            SchemeRecord(
                scheme_code=125497,
                scheme_name="SBI Small Cap Fund - Direct Plan - Growth",
                fund_house="SBI Mutual Fund",
                scheme_type="Open Ended Schemes",
                scheme_category="Equity Scheme - Small Cap Fund",
                isin_growth="INF200K01T51",
                isin_div_reinvestment=None,
                nav=999.0,
                nav_date=date(2026, 11, 20),
            )
        ]
    )
    store.refresh_latest()
    assert store.latest_for(125497)[1] == 999.0
    assert store.counts()["nav_rows"] == 6


def test_meta_and_integrity(store: Store):
    store.set_meta({"last_sync": "2026-11-21T00:00:00+00:00", "source": "AMFI India"})
    meta = store.get_meta()
    assert meta["source"] == "AMFI India"
    assert store.integrity_check() == "ok"
    assert store.has_data() is True
    assert store.nav_dates(2) == ["2026-11-20", "2026-11-17"]

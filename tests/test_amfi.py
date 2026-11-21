from __future__ import annotations

from datetime import date

from pipeline.amfi import decode_bytes, parse_history, parse_navall
from pipeline.dates import date_chunks, parse_flexible_date, to_api_date, to_iso


def test_parse_navall_metadata_and_rows(fixture):
    records = list(parse_navall(fixture("navall_sample.txt")))

    assert len(records) == 3
    first = records[0]
    assert first.scheme_code == 135762
    assert first.scheme_name == "Axis Children's Fund - Direct Plan - Growth Option"
    assert first.fund_house == "Axis Mutual Fund"
    assert first.scheme_type == "Open Ended Schemes"
    assert first.scheme_category == "Children's Fund - Childrens' Fund"
    assert first.isin_growth == "INF846K01WO1"
    assert first.isin_div_reinvestment is None
    assert first.nav == 31.6264
    assert first.nav_date == date(2026, 11, 20)


def test_parse_navall_skips_missing_nav(fixture):
    records = list(parse_navall(fixture("navall_sample.txt")))
    assert all(record.scheme_code != 125498 for record in records)


def test_parse_history_uses_full_nav_name(fixture):
    records = list(parse_history(fixture("navhistory_sample.txt")))
    assert len(records) == 4
    sbi = [record for record in records if record.scheme_code == 125497]
    assert {record.nav_date for record in sbi} == {
        date(2026, 11, 16),
        date(2026, 11, 17),
        date(2026, 11, 20),
    }
    assert sbi[0].scheme_name == "SBI Small Cap Fund - Direct Plan - Growth"
    assert sbi[0].scheme_category == "Equity Scheme - Small Cap Fund"

    hdfc = next(record for record in records if record.scheme_code == 100121)
    assert hdfc.scheme_type == "Close Ended Schemes"
    assert hdfc.scheme_category == "ELSS"
    assert hdfc.fund_house == "HDFC Mutual Fund"


def test_decode_cp1252_fallback():
    raw = "Axis Children\u2019s Fund".encode("cp1252")
    assert "Children" in decode_bytes(raw)


def test_date_helpers():
    assert parse_flexible_date("2026-11-20") == date(2026, 11, 20)
    assert parse_flexible_date("20-11-2026") == date(2026, 11, 20)
    assert parse_flexible_date("20-Nov-2026") == date(2026, 11, 20)
    assert to_api_date("2026-11-20") == "20-11-2026"
    assert to_iso(date(2026, 11, 20)) == "2026-11-20"


def test_date_chunks_are_inclusive_and_bounded():
    chunks = date_chunks(date(2026, 1, 1), date(2026, 1, 31), 10)
    assert chunks == [
        (date(2026, 1, 1), date(2026, 1, 10)),
        (date(2026, 1, 11), date(2026, 1, 20)),
        (date(2026, 1, 21), date(2026, 1, 30)),
        (date(2026, 1, 31), date(2026, 1, 31)),
    ]
    assert date_chunks(date(2026, 1, 2), date(2026, 1, 1), 10) == []

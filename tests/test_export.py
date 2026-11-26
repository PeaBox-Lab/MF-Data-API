from __future__ import annotations

import json

from pipeline.amfi import parse_history, parse_navall
from pipeline.config import Settings
from pipeline.export_static import export_static
from pipeline.store import Store


def test_static_export(tmp_path, fixture):
    db = tmp_path / "export.db"
    store = Store(db)
    store.init_schema()
    store.ingest(parse_navall(fixture("navall_sample.txt")))
    store.ingest(parse_history(fixture("navhistory_sample.txt")))
    store.refresh_latest()
    store.set_meta({"last_sync": "2026-11-21T00:00:00+00:00"})

    out = tmp_path / "public"
    summary = export_static(Settings(data_dir=tmp_path, db_override=db), out_dir=out)
    assert summary["schemes"] == 4
    assert summary["scheme_files"] == 4

    api = out / "api" / "v1"
    schemes = json.loads((api / "mf.json").read_text(encoding="utf-8"))
    assert len(schemes) == 4

    browse = json.loads((api / "mf" / "browse.json").read_text(encoding="utf-8"))
    assert len(browse) == 4
    sbi = next(row for row in browse if row["schemeCode"] == 125497)
    assert sbi["fundHouse"] == "SBI Mutual Fund"
    assert sbi["nav"] == "210.02130"
    assert sbi["date"] == "20-11-2026"

    latest = json.loads((api / "mf" / "latest.json").read_text(encoding="utf-8"))
    assert latest[0]["date"] == "20-11-2026"

    history = json.loads((api / "mf" / "125497.json").read_text(encoding="utf-8"))
    assert history["status"] == "SUCCESS"
    assert history["meta"]["scheme_name"] == "SBI Small Cap Fund - Direct Plan - Growth"
    assert [point["date"] for point in history["data"]] == [
        "20-11-2026",
        "17-11-2026",
        "16-11-2026",
    ]

    latest_one = json.loads(
        (api / "mf" / "125497" / "latest.json").read_text(encoding="utf-8")
    )
    assert len(latest_one["data"]) == 1

    stats = json.loads((api / "stats.json").read_text(encoding="utf-8"))
    assert stats["latest_nav_date"] == "20-11-2026"
    assert stats["scheme_count"] == 4

    assert (api / "fund-houses.json").exists()
    assert (api / "categories.json").exists()
    assert (api / "dates.json").exists()
    assert (api / "index.json").exists()


def test_static_export_history_limit(tmp_path, fixture):
    db = tmp_path / "limit.db"
    store = Store(db)
    store.init_schema()
    store.ingest(parse_history(fixture("navhistory_sample.txt")))
    store.refresh_latest()

    out = tmp_path / "public"
    export_static(
        Settings(data_dir=tmp_path, db_override=db),
        out_dir=out,
        history_days=-1,  # start date in the future: all fixture rows are filtered out
        include_latest=False,
    )
    # A future start date filters every fixture row out, so no scheme files are written.
    api = out / "api" / "v1"
    assert not (api / "mf" / "125497.json").exists()
    assert not (api / "mf" / "125497").exists()

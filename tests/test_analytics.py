from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from app.config import WEB_DIR, AppSettings
from app.main import create_app
from pipeline.analytics import (
    assign_theme,
    compute_daily_returns,
    compute_group_daily,
    normalize_category,
    scheme_family,
    write_analytics,
)
from pipeline.config import Settings
from pipeline.export_static import export_static
from pipeline.store import Store


def _analytics_db(tmp_path, name: str = "analytics.db"):
    db = tmp_path / name
    Store(db).init_schema()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executemany(
        "INSERT INTO schemes (scheme_code, scheme_name, fund_house, scheme_type, scheme_category) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (
                1,
                "ICICI Technology Fund - Direct Plan - Growth",
                "ICICI Mutual Fund",
                "Open Ended Schemes",
                "Equity Scheme - Sectoral/ Thematic",
            ),
            (
                2,
                "ICICI Technology Fund - Regular Plan - IDCW",
                "ICICI Mutual Fund",
                "Open Ended Schemes",
                "Equity Scheme - Sectoral/ Thematic",
            ),
            (
                3,
                "HDFC Banking Fund - Direct Plan - Growth",
                "HDFC Mutual Fund",
                "Open Ended Schemes",
                "Equity Schemes - Sectoral Fund",
            ),
            (
                4,
                "Old Stale Fund - Growth",
                "HDFC Mutual Fund",
                "Open Ended Schemes",
                "Equity Scheme - Small Cap Fund",
            ),
        ],
    )
    conn.executemany(
        "INSERT INTO nav_history (scheme_code, date, nav) VALUES (?, ?, ?)",
        [
            (1, "2026-11-18", 100.0),
            (1, "2026-11-19", 101.0),
            (1, "2026-11-20", 102.0),
            (2, "2026-11-18", 50.0),
            (2, "2026-11-19", 49.0),
            (3, "2026-11-18", 200.0),
            (3, "2026-11-19", 202.0),
            (4, "2026-11-01", 10.0),
            (4, "2026-11-20", 11.0),
        ],
    )
    conn.commit()
    returns = compute_daily_returns(conn)
    groups = compute_group_daily(returns)
    write_analytics(conn, returns, groups)
    conn.close()
    return db


def test_helpers_normalise_plans_and_categories():
    assert scheme_family("ICICI Technology Fund - Direct Plan - Growth") == scheme_family(
        "ICICI Technology Fund - Regular Plan - IDCW"
    )
    assert scheme_family("Franklin India Technology Fund-Growth") == "franklin india technology fund"
    assert normalize_category("Equity Schemes - Large Cap Fund") == "Equity Scheme - Large Cap Fund"
    assert normalize_category("Income/Debt Oriented Schemes - Liquid Fund") == "Debt Scheme - Liquid Fund"
    assert normalize_category("Childrens\ufffds Fund - Childrens' Fund") == (
        "Solution Oriented Scheme - Children's Fund"
    )
    assert assign_theme("ICICI Prudential Technology Fund - Growth") == "Information Technology"
    assert assign_theme("SBI Small Cap Fund - Direct Plan - Growth") is None


def test_daily_returns_dedupe_and_gap_handling(tmp_path):
    db = _analytics_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    codes = [row["scheme_code"] for row in conn.execute("SELECT DISTINCT scheme_code FROM scheme_daily_returns")]
    assert sorted(codes) == [1, 2, 3]  # stale fund excluded (19-day gap)

    canonical = {
        row["scheme_code"]: row["is_canonical"]
        for row in conn.execute("SELECT DISTINCT scheme_code, is_canonical FROM scheme_daily_returns")
    }
    assert canonical[1] == 1  # Direct Growth preferred
    assert canonical[2] == 0  # IDCW duplicate excluded from groups

    row = conn.execute(
        "SELECT * FROM scheme_daily_returns WHERE scheme_code = 1 AND date = '2026-11-19'"
    ).fetchone()
    assert abs(row["change_pct"] - 1.0) < 1e-6
    assert row["gap_days"] == 1
    conn.close()


def test_group_daily_aggregates(tmp_path):
    db = _analytics_db(tmp_path, "groups.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    it = conn.execute(
        "SELECT * FROM group_daily_kpis WHERE level = 'theme' AND grp = 'Information Technology' AND date = '2026-11-19'"
    ).fetchone()
    assert it["scheme_count"] == 1  # IDCW duplicate not counted
    assert abs(it["avg_change"] - 1.0) < 1e-6
    assert it["min_change"] == it["max_change"] == it["avg_change"]

    bank = conn.execute(
        "SELECT grp, avg_change FROM group_daily_kpis WHERE level = 'theme' AND date = '2026-11-19'"
    ).fetchall()
    assert any(row["grp"] == "Banking & Financial Services" for row in bank)

    categories = {
        row["grp"]
        for row in conn.execute("SELECT DISTINCT grp FROM group_daily_kpis WHERE level = 'category'")
    }
    assert "Equity Scheme - Sectoral Fund" in categories  # alias collapsed
    conn.close()


def test_analytics_api(tmp_path):
    db = _analytics_db(tmp_path, "api.db")
    settings = AppSettings(db_path=db, web_dir=WEB_DIR, rate_limit=0)
    client = TestClient(create_app(settings))

    summary = client.get("/api/v1/analytics/summary")
    assert summary.status_code == 200
    assert summary.json()["dateCount"] == 2
    assert summary.json()["groups"]["theme"] == 2

    groups = client.get("/api/v1/analytics/groups", params={"level": "theme"}).json()
    assert [row["name"] for row in groups] == ["Banking & Financial Services", "Information Technology"]

    movement = client.get(
        "/api/v1/analytics/movement",
        params={"level": "theme", "group": "Information Technology"},
    ).json()
    assert [row["date"] for row in movement["data"]] == ["19-11-2026", "20-11-2026"]
    assert abs(movement["data"][0]["avg_change"] - 1.0) < 1e-6
    assert movement["latestDate"] == "20-11-2026"

    ranking = client.get("/api/v1/analytics/movement", params={"level": "theme"}).json()
    assert ranking["group"] is None
    assert ranking["data"] == []  # fixture groups have fewer than 3 schemes

    ranking = client.get(
        "/api/v1/analytics/movement", params={"level": "theme", "minSchemes": 1}
    ).json()
    assert len(ranking["data"]) >= 1
    changes = [row["avg_change"] for row in ranking["data"]]
    assert changes == sorted(changes, reverse=True)

    filtered = client.get(
        "/api/v1/analytics/movement",
        params={"level": "theme", "group": "Information Technology", "startDate": "20-11-2026"},
    ).json()
    assert [row["date"] for row in filtered["data"]] == ["20-11-2026"]

    assert client.get("/api/v1/analytics/movement", params={"level": "nope"}).status_code == 422
    assert client.get("/api/v1/analytics/movement", params={"startDate": "bad"}).status_code == 400

    # The re-added KPI endpoints now use the configured store rather than a
    # non-existent module-level connection helper.
    missing_kpis = client.get("/api/v1/kpi/scheme/1")
    assert missing_kpis.status_code == 503


def test_static_export_includes_analytics(tmp_path):
    db = _analytics_db(tmp_path, "export.db")
    out = tmp_path / "public"
    export_static(Settings(data_dir=tmp_path, db_override=db), out_dir=out)

    api = out / "api" / "v1" / "analytics"
    summary = json.loads((api / "summary.json").read_text(encoding="utf-8"))
    groups = json.loads((api / "groups.json").read_text(encoding="utf-8"))
    movement = json.loads((api / "movement.json").read_text(encoding="utf-8"))

    assert summary["dateCount"] == 2
    assert "Information Technology" in [row["name"] for row in groups["theme"]]
    assert any(
        row["level"] == "theme" and row["group"] == "Information Technology"
        for row in movement
    )

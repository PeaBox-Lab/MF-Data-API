from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings, WEB_DIR
from app.main import create_app
from pipeline.amfi import parse_history, parse_navall
from pipeline.store import Store


@pytest.fixture()
def client(tmp_path, fixture) -> TestClient:
    db = tmp_path / "api.db"
    store = Store(db)
    store.init_schema()
    store.ingest(parse_navall(fixture("navall_sample.txt")))
    store.ingest(parse_history(fixture("navhistory_sample.txt")))
    store.refresh_latest()
    store.set_meta(
        {
            "last_sync": "2026-11-21T00:00:00+00:00",
            "source": "AMFI India",
        }
    )
    settings = AppSettings(db_path=db, web_dir=WEB_DIR, rate_limit=0)
    return TestClient(create_app(settings))


def test_latest_nav(client: TestClient):
    response = client.get("/api/v1/mf/125497/latest")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "SUCCESS"
    assert payload["meta"]["scheme_code"] == 125497
    assert payload["meta"]["scheme_name"] == "SBI Small Cap Fund - Direct Plan - Growth"
    assert payload["data"] == [{"date": "20-11-2026", "nav": "210.02130"}]


def test_history_with_date_filter(client: TestClient):
    response = client.get(
        "/api/v1/mf/125497?startDate=2026-11-17&endDate=2026-11-17"
    )
    assert response.status_code == 200
    assert response.json()["data"] == [{"date": "17-11-2026", "nav": "209.63760"}]

    response = client.get("/api/v1/mf/125497?startDate=20-11-2026")
    assert response.json()["data"] == [{"date": "20-11-2026", "nav": "210.02130"}]


def test_search_and_list(client: TestClient):
    response = client.get("/api/v1/mf/search", params={"q": "axis"})
    assert response.status_code == 200
    assert [row["schemeCode"] for row in response.json()] == [135762, 135765]

    response = client.get("/api/v1/mf", params={"limit": 2, "offset": 1})
    assert response.status_code == 200
    assert [row["schemeCode"] for row in response.json()] == [125497, 135762]

    response = client.get("/api/v1/mf", params={"fund_house": "HDFC Mutual Fund"})
    assert [row["schemeCode"] for row in response.json()] == [100121]


def test_latest_all_and_meta(client: TestClient):
    response = client.get("/api/v1/mf/latest")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 4
    assert rows[0] == {
        "schemeCode": 100121,
        "schemeName": "HDFC TaxSaver - Growth",
        "nav": "68.21400",
        "date": "20-11-2026",
    }

    response = client.get("/api/v1/mf/125497/meta")
    assert response.json()["isin_growth"] == "INF200K01T51"


def test_reference_endpoints(client: TestClient):
    houses = client.get("/api/v1/fund-houses").json()
    assert {row["fundHouse"] for row in houses} == {
        "Axis Mutual Fund",
        "HDFC Mutual Fund",
        "SBI Mutual Fund",
    }

    schemes = client.get("/api/v1/fund-houses/SBI%20Mutual%20Fund/schemes").json()
    assert [row["schemeCode"] for row in schemes] == [125497]

    categories = client.get("/api/v1/categories").json()
    assert any(row["schemeCategory"] == "ELSS" for row in categories)

    on_date = client.get("/api/v1/nav/20-11-2026").json()
    assert on_date["date"] == "20-11-2026"
    assert len(on_date["data"]) == 4

    dates = client.get("/api/v1/dates").json()
    assert dates == ["20-11-2026", "17-11-2026", "16-11-2026"]


def test_stats_health_and_compatibility(client: TestClient):
    stats = client.get("/api/v1/stats").json()
    assert stats["scheme_count"] == 4
    assert stats["nav_rows"] == 6
    assert stats["latest_nav_date"] == "20-11-2026"

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    # Root-level aliases mirror the /api/v1 routes.
    root = client.get("/mf/125497/latest")
    assert root.status_code == 200
    assert root.json()["meta"]["scheme_code"] == 125497


def test_errors(client: TestClient):
    missing = client.get("/api/v1/mf/999999")
    assert missing.status_code == 404
    assert missing.json()["status"] == "NOT_FOUND"

    bad_date = client.get("/api/v1/mf/125497", params={"startDate": "not-a-date"})
    assert bad_date.status_code == 400
    assert bad_date.json()["status"] == "BAD_REQUEST"

    reversed_range = client.get(
        "/api/v1/mf/125497",
        params={"startDate": "2026-11-20", "endDate": "2026-11-01"},
    )
    assert reversed_range.status_code == 400


def test_site_pages_and_openapi(client: TestClient):
    assert client.get("/").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/explorer").status_code == 200
    assert client.get("/assets/style.css").status_code == 200

    schema = client.get("/api/openapi.json").json()
    assert schema["info"]["title"] == "MF Data API"
    assert "/api/v1/mf/{scheme_code}" in schema["paths"]
    assert "/mf/{scheme_code}" not in schema["paths"]

    assert client.get("/not-a-page").status_code == 404


def test_cors_and_rate_limit(tmp_path, fixture):
    db = tmp_path / "rate.db"
    store = Store(db)
    store.init_schema()
    store.ingest(parse_navall(fixture("navall_sample.txt")))
    store.refresh_latest()

    settings = AppSettings(db_path=db, web_dir=WEB_DIR, rate_limit=2, rate_window=60)
    client = TestClient(create_app(settings))

    first = client.get(
        "/api/v1/mf",
        params={"limit": 1},
        headers={"Origin": "https://example.com"},
    )
    assert first.headers["x-ratelimit-limit"] == "2"
    assert first.headers["access-control-allow-origin"] == "*"

    client.get("/api/v1/mf", params={"limit": 1})
    limited = client.get("/api/v1/mf", params={"limit": 1})
    assert limited.status_code == 429
    assert limited.json()["status"] == "RATE_LIMITED"
    assert "retry-after" in limited.headers

    # Health checks are exempt from the limiter.
    assert client.get("/api/v1/health").status_code == 200

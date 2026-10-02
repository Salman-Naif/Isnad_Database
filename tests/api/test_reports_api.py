"""API tests: report endpoints and their input validation."""

import pytest

from app.db.sqlite import connection


def add_event(type_, created_at, visitor="v1", query=None, result=None, latency=None):
    with connection() as conn:
        conn.execute(
            """INSERT INTO events (type, visitor_hash, query, result, latency_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (type_, visitor, query, result, latency, created_at),
        )


@pytest.fixture
def activity(client):
    # Times are UTC; reports group by Saudi time (UTC+3).
    add_event("visit", "2026-09-01 10:00:00", visitor="a")
    add_event("visit", "2026-09-01 11:00:00", visitor="a")
    add_event("visit", "2026-09-01 22:30:00", visitor="b")  # 01:30 on Sep 2 in Saudi time
    add_event("search", "2026-09-01 10:01:00", visitor="a", query="إنما الأعمال", result="verified", latency=100)
    add_event("search", "2026-09-01 10:05:00", visitor="a", query="إنما الأعمال", result="verified", latency=300)
    add_event("search", "2026-09-01 11:00:00", visitor="a", query="اطلبوا العلم", result="no_match", latency=200)
    add_event("chat", "2026-09-01 10:02:00", visitor="a", query="ما حكمه؟")
    add_event("visit", "2026-08-15 10:00:00", visitor="c")  # outside the range below


def test_summary_endpoint_and_bad_ranges(admin_client, activity):
    res = admin_client.get("/api/reports/summary?from=2026-09-01&to=2026-09-01")
    assert res.status_code == 200
    assert res.json()["visits"] == 2

    assert admin_client.get("/api/reports/summary?from=2026-09-05&to=2026-09-01").status_code == 422
    assert admin_client.get("/api/reports/summary?from=2024-01-01&to=2026-09-01").status_code == 422
    assert admin_client.get("/api/reports/summary").status_code == 200  # default: last 30 days


def test_unknown_export_format(admin_client):
    assert admin_client.get("/api/reports/export?format=csv").status_code == 422

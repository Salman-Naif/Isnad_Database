"""API tests: the shape of every endpoint's response, its status codes and its errors.

These are the contract the dashboard's JavaScript and the main website rely on.
"""

import json

import pytest

HADITHS = [
    {"id": "h1", "text": "إنما الأعمال بالنيات", "hukm": "صحيح", "mohaddith": "البخاري",
     "sanad": [{"name": "عمر بن الخطاب", "grade": "صحابي"}], "topic": "النية", "source": "صحيح البخاري"},
]


def upload_hadiths(admin_client):
    body = json.dumps(HADITHS, ensure_ascii=False).encode()
    res = admin_client.post("/api/sources", files={"file": ("hadiths.json", body)})
    assert res.status_code == 202
    return res.json()


# --- Admin API ---


def test_me(admin_client):
    body = admin_client.get("/api/auth/me").json()
    assert set(body) == {"id", "username", "created_at", "must_change_password"}
    assert body["must_change_password"] is False


def test_admin_list_never_includes_password_hashes(admin_client):
    admins = admin_client.get("/api/admins").json()
    assert set(admins[0]) == {"id", "username", "created_at", "must_change_password"}
    assert "scrypt" not in json.dumps(admins)


def test_create_admin_returns_201_and_the_new_user(admin_client):
    res = admin_client.post("/api/admins", json={"username": "editor", "password": "long-enough-pass"})
    assert res.status_code == 201
    assert res.json()["username"] == "editor"


def test_delete_missing_admin_is_404(admin_client):
    assert admin_client.delete("/api/admins/999").status_code == 404


@pytest.mark.parametrize("body", [{}, {"username": "x"}, {"password": "y"}, {"username": "", "password": ""}])
def test_malformed_bodies_get_422_with_field_details(admin_client, body):
    res = admin_client.post("/api/admins", json=body)
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], list)


def test_source_row_shape(admin_client):
    row = upload_hadiths(admin_client)
    assert set(row) == {"id", "filename", "kind", "size_bytes", "chunks", "characters", "ocr_pages",
                        "uploaded_by", "uploaded_at", "status", "progress", "error"}
    listing = admin_client.get("/api/sources").json()
    assert set(listing) == {"sources", "total_files", "total_chunks"}
    assert listing["total_files"] == 1 and listing["total_chunks"] == 1


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/api/sources/999"), ("get", "/api/sources/999/download"), ("delete", "/api/sources/999"),
])
def test_missing_source_is_404(admin_client, method, path):
    assert getattr(admin_client, method)(path).status_code == 404


def test_non_numeric_ids_are_422(admin_client):
    assert admin_client.get("/api/sources/abc").status_code == 422
    assert admin_client.delete("/api/admins/abc").status_code == 422


def test_site_settings_round_trip(admin_client):
    defaults = admin_client.get("/api/site-settings").json()
    assert set(defaults) == {"maintenance_mode", "maintenance_message", "search_enabled", "chat_enabled",
                             "announcement", "main_site_url"}
    changed = {**defaults, "announcement": "إعلان", "chat_enabled": False}
    assert admin_client.put("/api/site-settings", json=changed).json() == changed
    assert admin_client.get("/api/site-settings").json() == changed


def test_status_shape(admin_client, monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    body = admin_client.get("/api/status").json()
    assert set(body) == {"checked_at", "checks"}
    assert len(body["checks"]) == 8
    for check in body["checks"]:
        assert set(check) == {"name", "ok", "detail", "latency_ms"}
        assert check["ok"] in (True, False, None)


def test_report_summary_shape(admin_client):
    body = admin_client.get("/api/reports/summary?from=2026-01-01&to=2026-01-07").json()
    assert len(body["daily"]) == 7
    for key in ("visits", "unique_visitors", "searches", "chats", "files", "chunks", "uploads_in_period"):
        assert isinstance(body[key], int)


@pytest.mark.parametrize(("fmt", "content_type", "magic"), [
    ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK"),
    ("pdf", "application/pdf", b"%PDF"),
])
def test_exports_are_downloadable_files(admin_client, fmt, content_type, magic):
    res = admin_client.get(f"/api/reports/export?format={fmt}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith(content_type)
    assert "attachment" in res.headers["content-disposition"] and f".{fmt}" in res.headers["content-disposition"]
    assert res.content.startswith(magic)


# --- Website API (/api/v1) ---


def test_site_config_shape(client, site_headers):
    body = client.get("/api/v1/site-config", headers=site_headers).json()
    assert {"maintenance_mode", "maintenance_message", "search_enabled", "chat_enabled", "announcement"} <= set(body)


def test_search_match_shape(client, admin_client, site_headers):
    upload_hadiths(admin_client)
    res = client.post("/api/v1/search", json={"query": "إنما الأعمال بالنيات", "top_k": 3}, headers=site_headers)
    assert res.status_code == 200
    [match] = res.json()["matches"]
    assert set(match) == {"id", "text", "similarity", "word_overlap", "kind", "hukm", "mohaddith", "sanad",
                          "sanad_tree", "sanad_extracted", "topic", "source", "compiler"}
    assert match["word_overlap"] == 1.0  # every word of the query is in the hadith
    assert 0.0 <= match["similarity"] <= 1.0
    assert match["sanad"] == [{"name": "عمر بن الخطاب", "grade": "صحابي"}]
    assert match["source"] == "صحيح البخاري"
    # The uploaded sanad, ending with the book's compiler.
    assert match["sanad_tree"] == {"name": "عمر بن الخطاب", "grade": "صحابي", "children": [
        {"name": "البخاري", "grade": None, "children": []}]}
    assert match["sanad_extracted"] is False


def test_topics_shape(client, admin_client, site_headers):
    upload_hadiths(admin_client)
    assert client.get("/api/v1/topics", headers=site_headers).json() == [{"name": "النية", "count": 1}]


def test_events_answer_204_with_no_body(client, site_headers):
    res = client.post("/api/v1/events", json={"type": "visit", "visitor_id": "abc"}, headers=site_headers)
    assert res.status_code == 204 and res.content == b""


def test_search_query_made_only_of_diacritics_is_rejected(client, site_headers):
    res = client.post("/api/v1/search", json={"query": "َُِ"}, headers=site_headers)
    assert res.status_code == 422

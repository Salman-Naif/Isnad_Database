"""Integration tests: the system status checks."""

import httpx


def statuses(admin_client) -> dict[str, dict]:
    res = admin_client.get("/api/status")
    assert res.status_code == 200
    return {c["name"]: c for c in res.json()["checks"]}


def test_status_reports_every_part(admin_client, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    checks = statuses(admin_client)

    assert checks["قاعدة بيانات التطبيق"]["ok"] is True
    assert checks["قاعدة البيانات المتجهية"]["ok"] is True
    assert checks["مفتاح الموقع الأساسي (SITE_API_KEY)"]["ok"] is True
    assert checks["مفتاح OpenRouter"]["ok"] is None  # not configured in tests
    assert checks["الموقع الأساسي"]["ok"] is None  # no URL saved yet
    assert checks["نموذج التمثيلات الدلالية"]["ok"] is None  # needs OPENROUTER_API_KEY
    assert "نموذج الحوار" not in checks  # the chat model belongs to the main website


def test_status_checks_the_main_site(admin_client, monkeypatch):
    admin_client.put("/api/site-settings", json={"main_site_url": "https://isnad.example.com"})
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200 if url.endswith("/health") else 404, json={}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    checks = statuses(admin_client)
    assert "https://isnad.example.com/health" in calls
    assert checks["الموقع الأساسي"]["ok"] is True


def test_status_flags_invalid_openrouter_key(admin_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "openrouter_api_key", "sk-or-v1-invalid")
    monkeypatch.setattr(
        httpx, "get",
        lambda url, **k: httpx.Response(401, json={}, request=httpx.Request("GET", url)),
    )
    assert statuses(admin_client)["مفتاح OpenRouter"]["ok"] is False

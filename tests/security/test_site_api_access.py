"""Security tests: only the website's key opens the website API."""



def test_site_api_requires_the_site_key(client):
    for method, path in [
        ("get", "/api/v1/site-config"),
        ("post", "/api/v1/search"),
        ("get", "/api/v1/topics"),
        ("post", "/api/v1/events"),
    ]:
        assert getattr(client, method)(path).status_code == 401
        assert getattr(client, method)(path, headers={"X-API-Key": "wrong"}).status_code == 401


def test_admin_login_does_not_open_the_site_api(admin_client):
    assert admin_client.get("/api/v1/site-config").status_code == 401


def test_site_api_unavailable_without_configured_key(client, site_headers, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "site_api_key", "")
    assert client.get("/api/v1/site-config", headers=site_headers).status_code == 503

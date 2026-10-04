"""Security tests: sign-in, sessions and access control of the dashboard."""


import pytest

from app.config import get_settings
from app.services import auth
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME


def login(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def upload(client, name: str, data: bytes):
    return client.post("/api/sources", files={"file": (name, data)})


def test_login_sets_httponly_strict_cookie(client, admin):
    res = login(client)
    assert res.status_code == 200
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/auth/me").json()["username"] == ADMIN_USERNAME


def test_login_username_is_case_insensitive(client, admin):
    assert login(client, username=ADMIN_USERNAME.upper()).status_code == 200


@pytest.mark.parametrize(("username", "password"), [
    (ADMIN_USERNAME, "wrong-password"),
    ("nobody", ADMIN_PASSWORD),
])
def test_login_rejects_bad_credentials(client, admin, username, password):
    res = login(client, username, password)
    assert res.status_code == 401
    assert "set-cookie" not in res.headers


def test_login_is_rate_limited(client, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_attempts_per_15_minutes", 3)
    for _ in range(3):
        login(client, password="wrong-password")
    assert login(client).status_code == 429  # even the right password is blocked now


def test_login_is_limited_per_account_whatever_the_address(client, admin, monkeypatch):
    """Fake X-Forwarded-For addresses dodge a per-IP limit; the account's own limit holds."""
    monkeypatch.setattr(get_settings(), "login_attempts_per_15_minutes", 1000)
    monkeypatch.setattr(get_settings(), "login_attempts_per_account_per_15_minutes", 3)
    monkeypatch.setattr("app.core.rate_limit.client_ip", lambda request: request.headers["x-forwarded-for"])
    for i in range(3):
        res = client.post("/api/auth/login", json={"username": ADMIN_USERNAME.upper(), "password": "wrong"},
                          headers={"X-Forwarded-For": f"10.0.0.{i}"})
        assert res.status_code == 401
    res = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
                      headers={"X-Forwarded-For": "10.0.0.99"})
    assert res.status_code == 429


def test_logout_ends_session(admin_client):
    assert admin_client.post("/api/auth/logout").status_code == 204
    assert admin_client.get("/api/auth/me").status_code == 401


def test_stolen_cookie_is_useless_after_logout(admin_client):
    token = admin_client.cookies.get("isnad_session")
    admin_client.post("/api/auth/logout")
    admin_client.cookies.set("isnad_session", token)
    assert admin_client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/api/sources"),
    ("post", "/api/sources"),
    ("get", "/api/sources/1/download"),
    ("delete", "/api/sources/1"),
    ("get", "/api/site-settings"),
    ("put", "/api/site-settings"),
    ("get", "/api/status"),
    ("get", "/api/reports/summary"),
    ("get", "/api/reports/export?format=xlsx"),
    ("get", "/api/admins"),
    ("post", "/api/admins"),
    ("delete", "/api/admins/1"),
])
def test_dashboard_api_rejects_anonymous_callers(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_site_key_does_not_open_the_dashboard_api(client, site_headers):
    # The main website's key only works on /api/v1 — it is not an admin login.
    assert client.get("/api/sources", headers=site_headers).status_code == 401


def test_dashboard_redirects_to_login(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/login"


def test_login_page_redirects_when_already_logged_in(admin_client):
    res = admin_client.get("/login", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/"


def test_login_page_reveals_nothing(client):
    html = client.get("/login").text
    assert "/api/v1" not in html and "sources" not in html


def test_deleted_admin_is_signed_out(admin_client, admin):
    other = auth.create_admin("second", "another-pass")
    token = auth.create_session(other.id)
    auth.delete_admin(other.id)
    assert auth.get_session_admin(token) is None


def test_password_change_signs_out_everywhere(admin_client):
    auth.set_password(ADMIN_USERNAME, "brand-new-password")
    assert admin_client.get("/api/auth/me").status_code == 401
    assert login(admin_client, password="brand-new-password").status_code == 200


def test_change_password_requires_login(client):
    res = client.post("/api/auth/change-password", json={"current_password": "x", "new_password": "y" * 10})
    assert res.status_code == 401


def test_default_user_with_short_password_must_change_it(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_username", "salman")
    monkeypatch.setattr(settings, "admin_password", "first1")
    auth.ensure_bootstrap_admin()

    res = login(client, "salman", "first1")
    assert res.status_code == 200
    assert res.json()["must_change_password"] is True
    assert "كلمة المرور الافتراضية" in client.get("/").text  # banner on the dashboard


def test_the_default_password_opens_nothing_but_the_password_form(client, monkeypatch):
    """The default password is public: until it is changed, the account can't act."""
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_username", "salman")
    monkeypatch.setattr(settings, "admin_password", "first1")
    auth.ensure_bootstrap_admin()
    login(client, "salman", "first1")

    for method, path in [("get", "/api/sources"), ("get", "/api/admins"), ("get", "/api/site-settings"),
                         ("delete", "/api/sources/1"), ("get", "/api/reports/summary")]:
        res = getattr(client, method)(path)
        assert res.status_code == 403, (path, res.status_code)
        assert "كلمة المرور الافتراضية" in res.json()["detail"]
    assert upload(client, "a.txt", "نص".encode()).status_code == 403
    assert client.post("/api/admins", json={"username": "x", "password": "long-enough-pass"}).status_code == 403
    assert client.get("/api/auth/me").status_code == 200

    res = client.post("/api/auth/change-password", json={"current_password": "first1", "new_password": "new-strong-pass"})
    assert res.status_code == 204
    assert client.get("/api/sources").status_code == 200


def test_upload_requires_login(client):
    assert upload(client, "a.txt", b"x").status_code == 401

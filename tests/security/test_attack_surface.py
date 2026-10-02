"""Security tests: every route's access rules, injection, uploads, sessions and secrets.

The API route list is read from the application itself (its OpenAPI schema), so a new
endpoint that forgets its access check fails here instead of shipping open. The HTML pages
(/, /login, /robots.txt) and /health are covered by their own tests.
"""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.config import get_settings
from app.core.security import hash_token
from app.db.sqlite import connection
from app.main import app
from app.services import auth, sources
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, SITE_API_KEY

# API routes anyone may call. Everything else needs an admin session or the website's key.
PUBLIC = {("POST", "/api/auth/login"), ("POST", "/api/auth/logout")}
SITE_KEY_ONLY = "/api/v1/"


def all_routes() -> list[tuple[str, str]]:
    return sorted(
        (method.upper(), path) for path, operations in app.openapi()["paths"].items() for method in operations
    )


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def call(client, method, path, **kwargs):
    return client.request(method, concrete(path), **kwargs)


ADMIN_ROUTES = [r for r in all_routes() if r not in PUBLIC and not r[1].startswith(SITE_KEY_ONLY)]
SITE_ROUTES = [r for r in all_routes() if r[1].startswith(SITE_KEY_ONLY)]


def test_route_inventory_is_what_we_expect():
    # A new route must be added here on purpose, with its access rule decided.
    assert len(ADMIN_ROUTES) == 15, ADMIN_ROUTES
    assert len(SITE_ROUTES) == 4, SITE_ROUTES
    assert set(all_routes()) >= PUBLIC


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_every_admin_route_rejects_anonymous_callers(client, method, path):
    assert call(client, method, path).status_code == 401


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_the_website_key_opens_no_admin_route(client, method, path):
    assert call(client, method, path, headers={"X-API-Key": SITE_API_KEY}).status_code == 401


@pytest.mark.parametrize(("method", "path"), SITE_ROUTES)
def test_every_site_route_needs_the_exact_key(client, method, path):
    for headers in ({}, {"X-API-Key": "wrong"}, {"X-API-Key": SITE_API_KEY[:-1]},
                    {"X-API-Key": SITE_API_KEY + "x"}, {"Authorization": f"Bearer {SITE_API_KEY}"}):
        assert call(client, method, path, headers=headers).status_code == 401


@pytest.mark.parametrize(("method", "path"), SITE_ROUTES)
def test_an_admin_session_opens_no_site_route(admin_client, method, path):
    assert call(admin_client, method, path).status_code == 401


# --- Sessions ---


def test_expired_session_is_rejected(admin_client):
    token = admin_client.cookies.get("isnad_session")
    past = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    with connection() as conn:
        conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (past, hash_token(token)))
    assert admin_client.get("/api/auth/me").status_code == 401


def test_forged_session_cookie_is_rejected(client, admin):
    client.cookies.set("isnad_session", "forged-token-value")
    assert client.get("/api/auth/me").status_code == 401


def test_database_never_holds_raw_tokens_or_passwords(admin_client):
    token = admin_client.cookies.get("isnad_session")
    with connection() as conn:
        dump = "\n".join(str(tuple(r)) for t in ("admins", "sessions") for r in conn.execute(f"SELECT * FROM {t}"))  # noqa: S608
    assert token not in dump
    assert ADMIN_PASSWORD not in dump


def test_cookie_is_secure_over_https(client, admin):
    res = client.post("https://testserver/api/auth/login",
                      json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert res.status_code == 200
    assert "secure" in res.headers["set-cookie"].lower()


def test_failed_logins_do_not_reveal_which_usernames_exist(client, admin):
    wrong_password = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": "nope-nope"})
    no_such_user = client.post("/api/auth/login", json={"username": "ghost", "password": "nope-nope"})
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json() == no_such_user.json()


def test_login_needs_json_so_other_sites_cannot_post_a_form(client, admin):
    # A cross-site HTML form can only send form data; the API accepts JSON only.
    res = client.post("/api/auth/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert res.status_code == 422
    assert "set-cookie" not in res.headers


def test_password_change_is_rate_limited(admin_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_attempts_per_15_minutes", 2)
    for _ in range(2):
        admin_client.post("/api/auth/change-password", json={"current_password": "guess", "new_password": "x" * 12})
    res = admin_client.post("/api/auth/change-password", json={"current_password": "guess", "new_password": "x" * 12})
    assert res.status_code == 429


# --- Injection ---

SQL_PAYLOADS = ["' OR '1'='1", "x'; DROP TABLE admins; --", "\" OR 1=1 --", "admin'--"]


@pytest.mark.parametrize("payload", SQL_PAYLOADS)
def test_sql_injection_in_login_is_inert(client, admin, payload):
    for body in ({"username": payload, "password": "x"}, {"username": ADMIN_USERNAME, "password": payload}):
        assert client.post("/api/auth/login", json=body).status_code == 401
    assert auth.count_admins() == 1  # the table is still there


@pytest.mark.parametrize("payload", SQL_PAYLOADS)
def test_sql_injection_in_search_and_events_is_inert(client, admin_client, site_headers, payload):
    assert client.post("/api/v1/search", json={"query": payload}, headers=site_headers).status_code == 200
    res = client.post("/api/v1/events", json={"type": "search", "query": payload, "visitor_id": payload},
                      headers=site_headers)
    assert res.status_code == 204
    top = admin_client.get("/api/reports/summary").json()["top_searches"]
    assert top[0]["label"] == payload  # stored as plain data


def test_hostile_file_names_are_stored_inside_the_uploads_folder(admin_client):
    res = admin_client.post("/api/sources", files={"file": ("../../../outside.txt", "الدين النصيحة لله".encode())})
    assert res.status_code == 202
    assert res.json()["filename"] == "outside.txt"
    stored = sources.stored_path("outside.txt").resolve()
    assert stored.is_relative_to(get_settings_uploads())


def get_settings_uploads():
    from pathlib import Path

    return Path(get_settings().uploads_dir).resolve()


def test_windows_style_traversal_is_neutralised(admin_client):
    res = admin_client.post("/api/sources", files={"file": ("..\\..\\evil.txt", "الدين النصيحة لله".encode())})
    if res.status_code == 202:
        assert sources.stored_path(res.json()["filename"]).resolve().is_relative_to(get_settings_uploads())
    else:
        assert res.status_code in (400, 415)


def test_file_names_with_markup_are_returned_as_data(admin_client):
    name = '<img src=x onerror=alert(1)>.txt'
    res = admin_client.post("/api/sources", files={"file": (name, "الدين النصيحة لله".encode())})
    assert res.status_code == 202
    # JSON is not HTML: the dashboard puts names into the page with textContent only.
    assert res.headers["content-type"].startswith("application/json")
    download = admin_client.get(f"/api/sources/{res.json()['id']}/download")
    assert download.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    assert "<" not in download.headers["content-disposition"]


def test_dashboard_scripts_never_inject_html():
    from app.config import BASE_DIR

    for js in (BASE_DIR / "app" / "static" / "js").glob("*.js"):
        code = js.read_text(encoding="utf-8")
        assert "innerHTML" not in code and "insertAdjacentHTML" not in code and "eval(" not in code, js.name


def test_templates_never_disable_escaping():
    from app.config import BASE_DIR

    for html in (BASE_DIR / "app" / "templates").glob("*.html"):
        text = html.read_text(encoding="utf-8")
        assert "|safe" not in text.replace(" ", "") and "autoescape false" not in text, html.name


def test_upload_type_is_checked_before_anything_is_stored(admin_client):
    for name in ("shell.php", "run.exe", "page.html", "noext", "archive.zip"):
        assert admin_client.post("/api/sources", files={"file": (name, b"data")}).status_code == 415
    assert admin_client.get("/api/sources").json()["sources"] == []


# --- Secrets and errors ---


def test_status_never_reveals_keys(admin_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", "sk-or-v1-supersecretvalue")
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    body = admin_client.get("/api/status").text
    assert "supersecretvalue" not in body and SITE_API_KEY not in body


def test_unexpected_errors_reveal_no_internals(client, site_headers, monkeypatch):
    from app.services.vector_store import VectorStore

    def crash(*a, **k):
        raise RuntimeError("secret internal detail at /app/services/x.py")

    monkeypatch.setattr(VectorStore, "count", crash)
    monkeypatch.setattr(VectorStore, "query", crash)
    no_raise = client.__class__(client.app, raise_server_exceptions=False)
    res = no_raise.post("/api/v1/search", json={"query": "نص"}, headers=site_headers)
    assert res.status_code == 500
    assert "secret internal detail" not in res.text and "Traceback" not in res.text

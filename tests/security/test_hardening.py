"""Security tests: response headers, crawler rules and what public endpoints reveal."""

import re

import pytest

from app.config import BASE_DIR


def responses(client, admin_client):
    return {
        "login page": client.get("/login"),
        "dashboard": admin_client.get("/"),
        "health": client.get("/health"),
        "API": admin_client.get("/api/sources"),
        "401": client.get("/api/sources"),
        "404": client.get("/no-such-page"),
        "static file": client.get("/static/css/style.css"),
    }


def test_every_response_has_security_headers(client, admin_client):
    for name, res in responses(client, admin_client).items():
        assert res.headers["x-robots-tag"] == "noindex, nofollow", name
        assert res.headers["x-frame-options"] == "DENY", name
        assert res.headers["x-content-type-options"] == "nosniff", name
        assert res.headers["referrer-policy"] == "no-referrer", name
        assert "max-age=" in res.headers["strict-transport-security"], name
        csp = res.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp, name
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp, name


def test_pages_and_api_are_never_cached(client, admin_client):
    for name, res in responses(client, admin_client).items():
        if name != "static file":
            assert res.headers["cache-control"] == "no-store", name


def test_pages_work_under_the_content_security_policy(client, admin_client):
    # The CSP allows no inline code or styles: the markup must not need any.
    for html in (client.get("/login").text, admin_client.get("/").text):
        assert not re.search(r"\sstyle=", html)
        assert not re.search(r"<script(?![^>]*\ssrc=)", html)
        assert not re.search(r"\son[a-z]+=", html)  # onclick=, onload=, ...
        # Links are relative: nothing is fetched from another host, and a wrong proxy scheme
        # can't turn them into http:// links on an https:// page.
        assert not re.search(r"""\s(?:src|href|action)=["']?(?:https?:)?//""", html)


def test_static_folder_serves_only_assets(client):
    assert client.get("/static/../app/config.py").status_code == 404
    assert client.get("/static/%2e%2e/%2e%2e/.env").status_code == 404
    served = {p.suffix for p in (BASE_DIR / "app" / "static").rglob("*") if p.is_file()}
    assert served <= {".css", ".js", ".svg", ".png", ".ico", ".woff2"}


def test_robots_txt_disallows_everything(client):
    assert client.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_off_by_default(client, path):
    # They would list every endpoint to anyone.
    assert client.get(path).status_code == 404


def test_health_is_public_and_reveals_nothing(client):
    assert client.get("/health").json() == {"status": "ok"}

"""API tests: user management and password change endpoints."""

import pytest

from app.config import get_settings
from app.services import auth
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME


def login(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_dashboard_for_logged_in_admin(admin_client):
    res = admin_client.get("/")
    assert res.status_code == 200
    assert ADMIN_USERNAME in res.text


def test_admin_can_add_and_delete_admins(admin_client):
    res = admin_client.post("/api/admins", json={"username": "second", "password": "another-pass"})
    assert res.status_code == 201
    new_id = res.json()["id"]
    assert [a["username"] for a in admin_client.get("/api/admins").json()] == ["admin", "second"]

    assert admin_client.delete(f"/api/admins/{new_id}").status_code == 204
    assert admin_client.delete(f"/api/admins/{new_id}").status_code == 404


def test_admin_cannot_delete_self(admin_client, admin):
    assert admin_client.delete(f"/api/admins/{admin.id}").status_code == 400


@pytest.mark.parametrize(("username", "password"), [
    ("admin", "another-pass"),  # duplicate
    ("x", "another-pass"),  # username too short
    ("new admin", "another-pass"),  # space in username
    ("newadmin", "short"),  # password too short
])
def test_invalid_new_admin_rejected(admin_client, username, password):
    res = admin_client.post("/api/admins", json={"username": username, "password": password})
    assert res.status_code == 422


def test_bootstrap_admin_created_once(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "owner-password")

    auth.ensure_bootstrap_admin()
    auth.ensure_bootstrap_admin()
    assert [a.username for a in auth.list_admins()] == ["owner"]

    # Once any admin exists, the env password no longer creates or changes anything.
    monkeypatch.setattr(settings, "admin_username", "someone-else")
    auth.ensure_bootstrap_admin()
    assert [a.username for a in auth.list_admins()] == ["owner"]


def test_change_own_password(admin_client):
    other_device = auth.create_session(auth.list_admins()[0].id)
    res = admin_client.post("/api/auth/change-password", json={
        "current_password": ADMIN_PASSWORD, "new_password": "a-much-better-password",
    })
    assert res.status_code == 204

    assert admin_client.get("/api/auth/me").status_code == 200  # this session stays signed in
    assert auth.get_session_admin(other_device) is None  # other devices are signed out
    admin_client.post("/api/auth/logout")
    assert login(admin_client, password=ADMIN_PASSWORD).status_code == 401
    assert login(admin_client, password="a-much-better-password").status_code == 200


def test_changing_password_clears_the_default_flag(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_username", "salman")
    monkeypatch.setattr(get_settings(), "admin_password", "123456")
    auth.ensure_bootstrap_admin()
    login(client, "salman", "123456")

    client.post("/api/auth/change-password", json={"current_password": "123456", "new_password": "new-strong-pass"})
    assert client.get("/api/auth/me").json()["must_change_password"] is False
    assert "كلمة المرور الافتراضية" not in client.get("/").text


@pytest.mark.parametrize(("current", "new", "message"), [
    ("wrong-password", "a-much-better-password", "الحالية غير صحيحة"),
    (ADMIN_PASSWORD, "short", "8 أحرف"),
    (ADMIN_PASSWORD, ADMIN_PASSWORD, "تختلف"),
])
def test_change_password_rejects_bad_input(admin_client, current, new, message):
    res = admin_client.post("/api/auth/change-password", json={"current_password": current, "new_password": new})
    assert res.status_code == 422
    assert message in res.json()["detail"]


def test_only_the_system_manager_adds_and_deletes_users(admin_client, client):
    # The oldest account manages users (here: «admin»; on the service, ADMIN_USERNAME «salman»)
    second = admin_client.post("/api/admins", json={"username": "second", "password": "another-pass"}).json()
    third = admin_client.post("/api/admins", json={"username": "third", "password": "another-pass"}).json()
    listed = {a["username"]: a["is_owner"] for a in admin_client.get("/api/admins").json()}
    assert listed == {"admin": True, "second": False, "third": False}

    admin_client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "second", "password": "another-pass"}).status_code == 200
    assert client.post("/api/admins", json={"username": "fourth", "password": "another-pass"}).status_code == 403
    assert client.delete(f"/api/admins/{third['id']}").status_code == 403
    owner = next(a for a in client.get("/api/admins").json() if a["is_owner"])
    assert client.delete(f"/api/admins/{owner['id']}").status_code == 403
    assert "إضافة المستخدمين وحذفهم لمدير النظام فقط" in client.get("/").text
    assert second["is_owner"] is False


def test_the_system_manager_can_never_be_deleted(admin, monkeypatch):
    from app.config import get_settings
    from app.services import auth

    monkeypatch.setattr(get_settings(), "admin_username", "salman")
    salman = auth.create_admin("salman", "salman-password")
    assert auth.owner_id() == salman.id  # ADMIN_USERNAME, though not the oldest account
    with pytest.raises(auth.AuthError, match="مدير النظام"):
        auth.delete_admin(salman.id)
    assert auth.delete_admin(admin.id)

"""
User accounts and login sessions.

Only authorized users can log in. Sessions are stored server-side so logging
out (or deleting a user, or changing a password) takes effect immediately.
"""

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.core.security import hash_password, hash_token, new_session_token, verify_password
from app.db.sqlite import connection

logger = logging.getLogger(__name__)

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 8

# Verified against when the username doesn't exist, so a failed login takes
# the same time either way and doesn't reveal which usernames are real.
_DUMMY_HASH = hash_password("not-a-real-password")


class AuthError(Exception):
    """Invalid account data (message is shown to the user)."""


@dataclass
class Admin:
    id: int
    username: str
    created_at: str = ""
    must_change_password: bool = False


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _validate_username(username: str) -> None:
    if not USERNAME_PATTERN.match(username):
        raise AuthError("اسم المستخدم: 3–32 حرفًا إنجليزيًا أو أرقامًا أو (_ . -)")


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"كلمة المرور يجب ألا تقل عن {MIN_PASSWORD_LENGTH} أحرف")


# --- Accounts ---


def create_admin(
    username: str,
    password: str,
    *,
    must_change_password: bool = False,
    enforce_password_policy: bool = True,
) -> Admin:
    username = username.strip()
    _validate_username(username)
    if enforce_password_policy:
        _validate_password(password)
    try:
        with connection() as conn:
            cur = conn.execute(
                "INSERT INTO admins (username, password_hash, must_change_password) VALUES (?, ?, ?)",
                (username, hash_password(password), int(must_change_password)),
            )
            return Admin(id=cur.lastrowid, username=username, must_change_password=must_change_password)
    except sqlite3.IntegrityError as exc:
        raise AuthError("اسم المستخدم مستخدم مسبقًا") from exc


def list_admins() -> list[Admin]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, username, created_at, must_change_password FROM admins ORDER BY id"
        ).fetchall()
    return [
        Admin(r["id"], r["username"], r["created_at"], bool(r["must_change_password"]))
        for r in rows
    ]


def count_admins() -> int:
    with connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]


def owner_id() -> int | None:
    """The system manager: the account named ADMIN_USERNAME (the default user), or the oldest
    account if there is none by that name. Only they add and delete users; no one deletes them."""
    name = get_settings().admin_username
    with connection() as conn:
        row = conn.execute("SELECT id FROM admins WHERE username = ?", (name,)).fetchone() if name else None
        row = row or conn.execute("SELECT id FROM admins ORDER BY id LIMIT 1").fetchone()
    return row[0] if row else None


def is_owner(admin: Admin) -> bool:
    return admin.id == owner_id()


def delete_admin(admin_id: int) -> bool:
    """Delete a user and all their sessions — never the system manager."""
    if admin_id == owner_id():
        raise AuthError("مدير النظام لا يمكن حذفه")
    with connection() as conn:
        return conn.execute("DELETE FROM admins WHERE id = ?", (admin_id,)).rowcount > 0


def set_password(username: str, password: str) -> bool:
    """Reset a password (command line) and sign the user out everywhere."""
    _validate_password(password)
    with connection() as conn:
        row = conn.execute("SELECT id FROM admins WHERE username = ?", (username,)).fetchone()
        if row is None:
            return False
        conn.execute(
            "UPDATE admins SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (hash_password(password), row["id"]),
        )
        conn.execute("DELETE FROM sessions WHERE admin_id = ?", (row["id"],))
    return True


def change_own_password(admin: Admin, current_password: str, new_password: str, keep_token: str) -> None:
    """Change a signed-in user's password from the dashboard.

    Requires the current password, so a session left open on a shared computer
    can't be used to take over the account. Other sessions are signed out; the
    one making the change stays signed in.
    """
    with connection() as conn:
        row = conn.execute(
            "SELECT password_hash FROM admins WHERE id = ?", (admin.id,)
        ).fetchone()
    if row is None or not verify_password(current_password, row["password_hash"]):
        raise AuthError("كلمة المرور الحالية غير صحيحة")
    _validate_password(new_password)
    if new_password == current_password:
        raise AuthError("كلمة المرور الجديدة يجب أن تختلف عن الحالية")

    with connection() as conn:
        conn.execute(
            "UPDATE admins SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (hash_password(new_password), admin.id),
        )
        conn.execute(
            "DELETE FROM sessions WHERE admin_id = ? AND token_hash != ?",
            (admin.id, hash_token(keep_token)),
        )


def authenticate(username: str, password: str) -> Admin | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, must_change_password FROM admins WHERE username = ?",
            (username.strip(),),
        ).fetchone()
    if row is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return Admin(row["id"], row["username"], must_change_password=bool(row["must_change_password"]))


def ensure_bootstrap_admin() -> None:
    """Create the default user (ADMIN_USERNAME / ADMIN_PASSWORD) if there are no users yet.

    The default password may be short, so the length rule is skipped here — instead
    the account is marked "must change" and the dashboard asks for a new password.
    """
    settings = get_settings()
    if not (settings.admin_username and settings.admin_password):
        return
    if count_admins() > 0:
        return
    try:
        create_admin(
            settings.admin_username,
            settings.admin_password,
            must_change_password=True,
            enforce_password_policy=False,
        )
        logger.info("Created default user %r — change its password after signing in", settings.admin_username)
    except AuthError as exc:
        logger.error("Could not create default user: %s", exc)


# --- Sessions ---


def create_session(admin_id: int) -> str:
    """Start a session and return the raw token (sent to the browser as a cookie)."""
    token = new_session_token()
    expires = datetime.now(UTC) + timedelta(hours=get_settings().session_hours)
    with connection() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_now(),))
        conn.execute(
            "INSERT INTO sessions (token_hash, admin_id, expires_at) VALUES (?, ?, ?)",
            (hash_token(token), admin_id, expires.strftime("%Y-%m-%d %H:%M:%S")),
        )
    return token


def get_session_admin(token: str) -> Admin | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT a.id, a.username, a.must_change_password FROM sessions s
               JOIN admins a ON a.id = s.admin_id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (hash_token(token), _now()),
        ).fetchone()
    if row is None:
        return None
    return Admin(row["id"], row["username"], must_change_password=bool(row["must_change_password"]))


def delete_session(token: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))

"""
Dependencies shared across routes.

The model and the database connection are expensive, so they are loaded
only once and reused across all requests.

Two kinds of callers:
  - admins, identified by the session cookie set at login (dashboard and /api/*)
  - the main Isnad website, identified by SITE_API_KEY in the X-API-Key header (/api/v1/*)
"""

import hmac
from functools import lru_cache

from fastapi import Depends, Header, HTTPException, Request, status

from app.config import get_settings
from app.services import auth
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore

SESSION_COOKIE = "isnad_session"


@lru_cache
def get_embedder() -> EmbeddingService:
    """Single shared instance of the embedding model."""
    return EmbeddingService()


@lru_cache
def get_vector_store() -> VectorStore:
    """Single shared connection to the vector database."""
    return VectorStore()


def get_current_admin(request: Request) -> auth.Admin | None:
    """The logged-in admin, or None."""
    token = request.cookies.get(SESSION_COOKIE)
    return auth.get_session_admin(token) if token else None


def require_signed_in(admin: auth.Admin | None = Depends(get_current_admin)) -> auth.Admin:
    """Reject the request with 401 unless an admin is logged in (default password or not)."""
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="يجب تسجيل الدخول",
        )
    return admin


def require_admin(admin: auth.Admin = Depends(require_signed_in)) -> auth.Admin:
    """A logged-in admin who has replaced the default password.

    The default password is public (it is in the README), so until it is changed the account
    can only see who it is and change the password — not upload, delete or control the site.
    """
    if admin.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="غيّر كلمة المرور الافتراضية أولًا من صفحة «المستخدمون»",
        )
    return admin


def require_owner(admin: auth.Admin = Depends(require_admin)) -> auth.Admin:
    """The system manager — the only one who adds and deletes users."""
    if not auth.is_owner(admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="إضافة المستخدمين وحذفهم لمدير النظام فقط"
        )
    return admin


def require_site_key(x_api_key: str | None = Header(default=None)) -> None:
    """Reject the request unless it carries the main website's SITE_API_KEY."""
    expected = get_settings().site_api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SITE_API_KEY is not configured on the database service",
        )
    # Constant-time comparison, so the key can't be guessed from response timing.
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

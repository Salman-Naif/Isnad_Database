"""
Isnad database service — entry point.

A standalone service with its own URL, separate from the main website:
  - the admin dashboard (/)            upload sources, control the website, reports
  - the admin API (/api/...)           used by the dashboard, requires an admin login
  - the website API (/api/v1/...)      used by the main website, requires SITE_API_KEY
Nothing here is public except /health and the login page.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api.deps import get_vector_store
from app.api.routes import admins, auth, control, health, pages, reports, site_api, sources
from app.config import BASE_DIR, get_settings
from app.core.logging import setup_logging
from app.db.sqlite import init_db
from app.services.auth import ensure_bootstrap_admin
from app.services.sources import recover_interrupted, schedule_index_rebuild

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

SECURITY_HEADERS = {
    # Only the service's own scripts, styles and API: an injected script can't run, and
    # nothing is loaded from another site.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    ),
    # Browsers only ever reach the dashboard over HTTPS once they have seen it (Railway
    # serves HTTPS; the header is ignored on plain-HTTP localhost).
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    # Never indexed by search engines, never framed by another site, no MIME sniffing,
    # no referrer leaking the service URL to external links.
    "X-Robots-Tag": "noindex, nofollow",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    ensure_bootstrap_admin()
    recover_interrupted()
    # In the indexing queue, after any upload: the literal index in its current form.
    schedule_index_rebuild()
    # Open the vector database (and load chromadb/numpy) once, on the main thread, before
    # any request thread or the background worker can import them concurrently.
    try:
        get_vector_store().count()
    except Exception:
        logger.exception("Vector database could not be opened at startup")
    yield


app = FastAPI(
    title="Isnad Database",
    version="0.2.0",
    lifespan=lifespan,
    # The docs list every endpoint — off unless ENABLE_API_DOCS=true.
    docs_url="/docs" if settings.enable_api_docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.enable_api_docs else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")

app.include_router(pages.router)
app.include_router(health.router)

# Admin API (dashboard) — session cookie
app.include_router(auth.router, prefix="/api")
app.include_router(admins.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
app.include_router(control.router, prefix="/api")
app.include_router(reports.router, prefix="/api")

# Main website API — SITE_API_KEY
app.include_router(site_api.router, prefix="/api")

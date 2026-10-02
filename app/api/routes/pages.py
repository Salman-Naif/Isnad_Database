"""
HTML pages of the database service. There is no public content:
every page is either the login form or requires a logged-in admin.

  /login   sign-in
  /        dashboard (status, sources, website controls, reports, admins)
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import get_current_admin
from app.config import BASE_DIR, get_settings
from app.services.auth import Admin

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

router = APIRouter(include_in_schema=False)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, admin: Admin | None = Depends(get_current_admin)):
    if admin is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, admin: Admin | None = Depends(get_current_admin)):
    if admin is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"admin": admin, "max_upload_mb": get_settings().max_upload_mb},
    )


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    return "User-agent: *\nDisallow: /\n"

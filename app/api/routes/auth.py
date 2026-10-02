"""
Sign in, sign out, and change your own password.

The session cookie is HttpOnly (unreadable by page scripts) and SameSite=Strict
(never sent on requests from other sites, which blocks CSRF on the admin API).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.deps import SESSION_COOKIE, require_signed_in
from app.config import get_settings
from app.core import rate_limit
from app.core.rate_limit import rate_limited
from app.models.schemas import AdminInfo, ChangePasswordRequest, LoginRequest
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=AdminInfo,
    dependencies=[Depends(rate_limited("login", "login_attempts_per_15_minutes", 15 * 60))],
)
def login(payload: LoginRequest, request: Request, response: Response) -> AdminInfo:
    # Also per account: the per-IP limit alone can be dodged with made-up forwarded addresses.
    rate_limit.check(
        "login-account", payload.username.strip().casefold(),
        get_settings().login_attempts_per_account_per_15_minutes, 15 * 60,
    )
    admin = auth.authenticate(payload.username, payload.password)
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="اسم المستخدم أو كلمة المرور غير صحيحة",
        )
    response.set_cookie(
        SESSION_COOKIE,
        auth.create_session(admin.id),
        max_age=get_settings().session_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    return AdminInfo(
        id=admin.id, username=admin.username, must_change_password=admin.must_change_password
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth.delete_session(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=AdminInfo)
def me(admin: auth.Admin = Depends(require_signed_in)) -> AdminInfo:
    return AdminInfo(
        id=admin.id, username=admin.username, must_change_password=admin.must_change_password
    )


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    # Same limit as login: the current password must not be guessable through this form.
    dependencies=[Depends(rate_limited("change-password", "login_attempts_per_15_minutes", 15 * 60))],
)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    admin: auth.Admin = Depends(require_signed_in),
) -> Response:
    try:
        auth.change_own_password(
            admin,
            payload.current_password,
            payload.new_password,
            keep_token=request.cookies.get(SESSION_COOKIE, ""),
        )
    except auth.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

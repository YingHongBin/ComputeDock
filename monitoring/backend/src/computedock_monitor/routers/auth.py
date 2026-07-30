from __future__ import annotations

import hmac

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import SESSION_COOKIE, AuthContext, require_admin, require_csrf
from ..config import Settings, get_settings
from ..database import get_db
from ..models import Admin, AdminSession
from ..proxy_prefix import prefix_path, request_prefix
from ..schemas import AdminView, ChangePasswordRequest, LoginRequest
from ..security import digest_secret, hash_password, make_session, utcnow, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
CSRF_COOKIE = "computedock_monitor_csrf"


@router.post("/login", response_model=AdminView)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AdminView:
    db.execute(delete(AdminSession).where(AdminSession.expires_at <= utcnow()))
    admin = db.scalar(select(Admin).where(Admin.username == payload.username))
    if admin is None or not verify_password(admin.password_hash, payload.password):
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    generated = make_session(settings.session_hours)
    db.add(
        AdminSession(
            admin_id=admin.id,
            token_hash=generated.token_hash,
            csrf_hash=generated.csrf_hash,
            expires_at=generated.expires_at,
            created_at=utcnow(),
        )
    )
    db.commit()
    max_age = settings.session_hours * 3600
    cookie_path = prefix_path(request_prefix(request))
    response.set_cookie(
        SESSION_COOKIE,
        generated.token,
        max_age=max_age,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
        path=cookie_path,
    )
    response.set_cookie(
        CSRF_COOKIE,
        generated.csrf_token,
        max_age=max_age,
        secure=settings.cookie_secure,
        httponly=False,
        samesite="lax",
        path=cookie_path,
    )
    return AdminView(username=admin.username, csrf_token=generated.csrf_token)


@router.get("/me", response_model=AdminView)
def me(
    auth: AuthContext = Depends(require_admin),
    csrf_token: str | None = Cookie(default=None, alias=CSRF_COOKIE),
) -> AdminView:
    if not csrf_token or not hmac.compare_digest(digest_secret(csrf_token), auth.session.csrf_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "CSRF cookie missing")
    return AdminView(username=auth.admin.username, csrf_token=csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    db.delete(auth.session)
    db.commit()
    cookie_path = prefix_path(request_prefix(request))
    response.delete_cookie(SESSION_COOKIE, path=cookie_path)
    response.delete_cookie(CSRF_COOKIE, path=cookie_path)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    if not verify_password(auth.admin.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "current password is incorrect")
    auth.admin.password_hash = hash_password(payload.new_password)
    auth.admin.updated_at = utcnow()
    db.execute(
        delete(AdminSession).where(
            AdminSession.admin_id == auth.admin.id,
            AdminSession.id != auth.session.id,
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

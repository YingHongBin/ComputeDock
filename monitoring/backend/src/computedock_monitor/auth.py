from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Admin, AdminSession
from .security import digest_secret, utcnow

SESSION_COOKIE = "computedock_monitor_session"


@dataclass(frozen=True)
class AuthContext:
    admin: Admin
    session: AdminSession


def require_admin(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    record = db.scalar(
        select(AdminSession).where(AdminSession.token_hash == digest_secret(session_token))
    )
    if record is None or record.expires_at <= utcnow():
        if record is not None:
            db.delete(record)
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    admin = db.get(Admin, record.admin_id)
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "administrator not found")
    return AuthContext(admin=admin, session=record)


def require_csrf(
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    auth: AuthContext = Depends(require_admin),
) -> AuthContext:
    if not csrf_token or not hmac.compare_digest(digest_secret(csrf_token), auth.session.csrf_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid CSRF token")
    return auth


def parse_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bearer token")
    return token

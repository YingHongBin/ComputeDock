from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import AdminSession, User
from .security import digest_secret, is_expired

SESSION_COOKIE = "computedock_monitor_session"


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AdminSession

    @property
    def admin(self) -> User:
        """Compatibility alias while management routes move to role-aware auth."""
        return self.user


def require_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    record = db.scalar(
        select(AdminSession).where(AdminSession.token_hash == digest_secret(session_token))
    )
    if record is None or is_expired(record.expires_at):
        if record is not None:
            db.delete(record)
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    user_id = record.user_id or record.admin_id
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    if user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account disabled")
    return AuthContext(user=user, session=record)


def require_admin(auth: AuthContext = Depends(require_user)) -> AuthContext:
    if auth.user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "administrator required")
    return auth


def require_user_csrf(
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    auth: AuthContext = Depends(require_user),
) -> AuthContext:
    if not csrf_token or not hmac.compare_digest(digest_secret(csrf_token), auth.session.csrf_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid CSRF token")
    return auth


def require_admin_csrf(auth: AuthContext = Depends(require_user_csrf)) -> AuthContext:
    if auth.user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "administrator required")
    return auth


# Kept for existing imports; mutating management APIs are administrator-only until
# explicitly moved to require_user_csrf.
require_csrf = require_admin_csrf


def parse_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bearer token")
    return token

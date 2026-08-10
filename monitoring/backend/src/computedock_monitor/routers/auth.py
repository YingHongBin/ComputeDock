from __future__ import annotations

import hmac
import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import (
    SESSION_COOKIE,
    AuthContext,
    require_user,
    require_user_csrf,
)
from ..config import Settings, get_settings
from ..database import get_db
from ..models import AdminSession, EmailActionToken, RegistrationRequest, User
from ..notifications import (
    action_url,
    enqueue_admin_notice,
    enqueue_notification,
    issue_action_token,
)
from ..proxy_prefix import prefix_path, request_prefix
from ..schemas import (
    AdminView,
    ChangePasswordRequest,
    EmailChangeRequest,
    EmailTokenInput,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegistrationInput,
)
from ..security import (
    digest_secret,
    hash_password,
    is_expired,
    make_session,
    utcnow,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
CSRF_COOKIE = "computedock_monitor_csrf"


def session_view(user: User, csrf_token: str) -> AdminView:
    return AdminView(
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        must_bind_email=user.must_bind_email,
        role=user.role,  # type: ignore[arg-type]
        csrf_token=csrf_token,
    )


def set_session_cookies(
    response: Response,
    request: Request,
    settings: Settings,
    token: str,
    csrf_token: str,
) -> None:
    max_age = settings.session_hours * 3600
    cookie_path = prefix_path(request_prefix(request))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
        path=cookie_path,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        secure=settings.cookie_secure,
        httponly=False,
        samesite="lax",
        path=cookie_path,
    )


def matching_active_registration(
    db: Session, username: str, email: str
) -> RegistrationRequest | None:
    now = utcnow()
    requests = list(
        db.scalars(
            select(RegistrationRequest).where(
                RegistrationRequest.status.in_(("email_pending", "pending")),
                or_(
                    func.lower(RegistrationRequest.username) == username.lower(),
                    func.lower(RegistrationRequest.email) == email.lower(),
                ),
            )
        )
    )
    for registration in requests:
        if registration.status == "email_pending":
            valid_token = db.scalar(
                select(EmailActionToken.id).where(
                    EmailActionToken.registration_request_id == registration.id,
                    EmailActionToken.purpose == "registration_verify",
                    EmailActionToken.consumed_at.is_(None),
                    EmailActionToken.expires_at > now,
                )
            )
            if valid_token is None:
                registration.status = "rejected"
                registration.review_comment = "邮箱验证已过期"
                registration.reviewed_at = now
                registration.updated_at = now
                continue
        return registration
    return None


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
def register(
    payload: RegistrationInput,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    existing_user = db.scalar(
        select(User.id).where(
            or_(
                func.lower(User.username) == payload.username.lower(),
                func.lower(User.email) == payload.email.lower(),
            )
        )
    )
    if existing_user is not None or matching_active_registration(
        db, payload.username, payload.email
    ):
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "username or email is unavailable")
    now = utcnow()
    registration = RegistrationRequest(
        id=uuid.uuid4(),
        username=payload.username,
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        status="email_pending",
        created_at=now,
        updated_at=now,
    )
    db.add(registration)
    email_token, secret = issue_action_token(
        db,
        purpose="registration_verify",
        registration_request_id=registration.id,
    )
    enqueue_notification(
        db,
        idempotency_key=f"registration-verify:{registration.id}:{email_token.id}",
        template="registration_verify",
        to_address=registration.email,
        payload={
            "full_name": registration.full_name,
            "action_url": action_url(db, settings, "/verify-email", secret),
            "expires_hours": 24,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "username or email is unavailable") from exc
    return {"status": "verification_sent"}


@router.post("/registration/resend", status_code=status.HTTP_202_ACCEPTED)
def resend_registration_verification(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Send a fresh link without revealing whether a pending registration exists."""
    identity = payload.identity.strip().lower()
    registration = db.scalar(
        select(RegistrationRequest)
        .where(
            RegistrationRequest.status == "email_pending",
            or_(
                func.lower(RegistrationRequest.username) == identity,
                func.lower(RegistrationRequest.email) == identity,
            ),
        )
        .order_by(RegistrationRequest.created_at.desc())
    )
    if registration is not None:
        email_token, secret = issue_action_token(
            db,
            purpose="registration_verify",
            registration_request_id=registration.id,
        )
        enqueue_notification(
            db,
            idempotency_key=f"registration-verify:{registration.id}:{email_token.id}",
            template="registration_verify",
            to_address=registration.email,
            payload={
                "full_name": registration.full_name,
                "action_url": action_url(db, settings, "/verify-email", secret),
                "expires_hours": 24,
            },
        )
        registration.updated_at = utcnow()
        db.commit()
    return {"status": "verification_sent"}


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
def verify_registration_email(
    payload: EmailTokenInput,
    db: Session = Depends(get_db),
) -> Response:
    now = utcnow()
    token = db.scalar(
        select(EmailActionToken)
        .where(
            EmailActionToken.token_hash == digest_secret(payload.token),
            EmailActionToken.purpose == "registration_verify",
        )
        .with_for_update()
    )
    if token is None or token.consumed_at is not None or is_expired(token.expires_at, now):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "verification link is invalid or expired")
    registration = db.get(RegistrationRequest, token.registration_request_id)
    if registration is None or registration.status != "email_pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "registration is no longer pending")
    conflict = db.scalar(
        select(User.id).where(
            or_(
                func.lower(User.username) == registration.username.lower(),
                func.lower(User.email) == registration.email.lower(),
            )
        )
    )
    if conflict is not None:
        registration.status = "rejected"
        registration.review_comment = "用户名或邮箱已被使用"
        registration.reviewed_at = now
        registration.updated_at = now
        token.consumed_at = now
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "username or email is unavailable")
    token.consumed_at = now
    registration.status = "pending"
    registration.email_verified_at = now
    registration.updated_at = now
    enqueue_admin_notice(
        db,
        idempotency_key=f"registration-pending:{registration.id}",
        template="registration_pending_admin",
        payload={
            "username": registration.username,
            "full_name": registration.full_name,
            "email": registration.email,
        },
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/login", response_model=AdminView)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AdminView:
    db.execute(delete(AdminSession).where(AdminSession.expires_at <= utcnow()))
    user = db.scalar(
        select(User).where(func.lower(User.username) == payload.username.lower())
    )
    if user is None or not verify_password(user.password_hash, payload.password):
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    if user.status != "active":
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account disabled")
    generated = make_session(settings.session_hours)
    db.add(
        AdminSession(
            user_id=user.id,
            token_hash=generated.token_hash,
            csrf_hash=generated.csrf_hash,
            expires_at=generated.expires_at,
            created_at=utcnow(),
        )
    )
    db.commit()
    set_session_cookies(response, request, settings, generated.token, generated.csrf_token)
    return session_view(user, generated.csrf_token)


@router.get("/me", response_model=AdminView)
def me(
    auth: AuthContext = Depends(require_user),
    csrf_token: str | None = Cookie(default=None, alias=CSRF_COOKIE),
) -> AdminView:
    if not csrf_token or not hmac.compare_digest(digest_secret(csrf_token), auth.session.csrf_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "CSRF cookie missing")
    return session_view(auth.user, csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(require_user_csrf),
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
    auth: AuthContext = Depends(require_user_csrf),
    db: Session = Depends(get_db),
) -> Response:
    if not verify_password(auth.user.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "current password is incorrect")
    auth.user.password_hash = hash_password(payload.new_password)
    auth.user.updated_at = utcnow()
    db.execute(
        delete(AdminSession).where(
            or_(AdminSession.user_id == auth.user.id, AdminSession.admin_id == auth.user.id),
            AdminSession.id != auth.session.id,
        )
    )
    if auth.user.email and auth.user.email_verified_at:
        enqueue_notification(
            db,
            idempotency_key=f"password-changed:{auth.user.id}:{auth.user.updated_at.isoformat()}",
            template="password_changed",
            to_address=auth.user.email,
            payload={"full_name": auth.user.full_name},
        )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/reset-request", status_code=status.HTTP_204_NO_CONTENT)
def request_password_reset(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    identity = payload.identity.strip().lower()
    user = db.scalar(
        select(User).where(
            User.status == "active",
            or_(func.lower(User.username) == identity, func.lower(User.email) == identity),
        )
    )
    if user is not None and user.email and user.email_verified_at is not None:
        token, secret = issue_action_token(db, purpose="password_reset", user_id=user.id)
        enqueue_notification(
            db,
            idempotency_key=f"password-reset:{token.id}",
            template="password_reset",
            to_address=user.email,
            payload={
                "full_name": user.full_name,
                "action_url": action_url(db, settings, "/reset-password", secret),
                "expires_minutes": 30,
            },
        )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    payload: PasswordResetConfirm,
    db: Session = Depends(get_db),
) -> Response:
    now = utcnow()
    token = db.scalar(
        select(EmailActionToken)
        .where(
            EmailActionToken.token_hash == digest_secret(payload.token),
            EmailActionToken.purpose == "password_reset",
        )
        .with_for_update()
    )
    if token is None or token.consumed_at is not None or is_expired(token.expires_at, now):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reset link is invalid or expired")
    user = db.get(User, token.user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reset link is invalid or expired")
    user.password_hash = hash_password(payload.new_password)
    user.updated_at = now
    token.consumed_at = now
    db.execute(
        delete(AdminSession).where(
            or_(AdminSession.user_id == user.id, AdminSession.admin_id == user.id)
        )
    )
    if user.email:
        enqueue_notification(
            db,
            idempotency_key=f"password-reset-complete:{token.id}",
            template="password_changed",
            to_address=user.email,
            payload={"full_name": user.full_name},
        )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/email/change-request", status_code=status.HTTP_202_ACCEPTED)
def request_email_change(
    payload: EmailChangeRequest,
    auth: AuthContext = Depends(require_user_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if not verify_password(auth.user.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "current password is incorrect")
    conflict = db.scalar(
        select(User.id).where(
            func.lower(User.email) == payload.new_email.lower(), User.id != auth.user.id
        )
    )
    pending_conflict = db.scalar(
        select(RegistrationRequest.id).where(
            func.lower(RegistrationRequest.email) == payload.new_email.lower(),
            RegistrationRequest.status.in_(("email_pending", "pending")),
        )
    )
    if conflict is not None or pending_conflict is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email is unavailable")
    token, secret = issue_action_token(
        db,
        purpose="email_change",
        user_id=auth.user.id,
        pending_email=payload.new_email,
    )
    enqueue_notification(
        db,
        idempotency_key=f"email-change:{token.id}",
        template="email_change_verify",
        to_address=payload.new_email,
        payload={
            "full_name": auth.user.full_name,
            "action_url": action_url(db, settings, "/verify-new-email", secret),
            "expires_hours": 24,
        },
    )
    db.commit()
    return {"status": "verification_sent"}


@router.post("/email/change-confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_email_change(
    payload: EmailTokenInput,
    db: Session = Depends(get_db),
) -> Response:
    now = utcnow()
    token = db.scalar(
        select(EmailActionToken)
        .where(
            EmailActionToken.token_hash == digest_secret(payload.token),
            EmailActionToken.purpose == "email_change",
        )
        .with_for_update()
    )
    if (
        token is None
        or token.consumed_at is not None
        or is_expired(token.expires_at, now)
        or not token.pending_email
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "verification link is invalid or expired")
    user = db.get(User, token.user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "verification link is invalid or expired")
    conflict = db.scalar(
        select(User.id).where(
            func.lower(User.email) == token.pending_email.lower(), User.id != user.id
        )
    )
    if conflict is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email is unavailable")
    old_email = user.email
    user.email = token.pending_email
    user.email_verified_at = now
    user.must_bind_email = False
    user.updated_at = now
    token.consumed_at = now
    for address, suffix in ((old_email, "old"), (user.email, "new")):
        if address:
            enqueue_notification(
                db,
                idempotency_key=f"email-changed:{token.id}:{suffix}",
                template="email_changed",
                to_address=address,
                payload={"full_name": user.full_name, "new_email": user.email},
            )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

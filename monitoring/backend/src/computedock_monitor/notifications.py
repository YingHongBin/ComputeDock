from __future__ import annotations

import uuid
from datetime import timedelta
from urllib.parse import urlencode

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import Settings
from .models import EmailActionToken, NotificationOutbox, SystemSetting, User
from .security import digest_secret, make_email_action_token, utcnow

ACTION_TOKEN_LIFETIMES = {
    "registration_verify": timedelta(hours=24),
    "password_reset": timedelta(minutes=30),
    "email_change": timedelta(hours=24),
}


def enqueue_notification(
    db: Session,
    *,
    idempotency_key: str,
    template: str,
    to_address: str,
    payload: dict[str, object],
    cc_addresses: list[str] | None = None,
) -> NotificationOutbox:
    existing = db.scalar(
        select(NotificationOutbox).where(NotificationOutbox.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing
    now = utcnow()
    notification = NotificationOutbox(
        id=uuid.uuid4(),
        idempotency_key=idempotency_key,
        template=template,
        to_address=to_address,
        cc_addresses=cc_addresses or [],
        payload=payload,
        status="pending",
        attempts=0,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(notification)
    return notification


def issue_action_token(
    db: Session,
    *,
    purpose: str,
    user_id: uuid.UUID | None = None,
    registration_request_id: uuid.UUID | None = None,
    pending_email: str | None = None,
) -> tuple[EmailActionToken, str]:
    now = utcnow()
    filters = [EmailActionToken.purpose == purpose, EmailActionToken.consumed_at.is_(None)]
    if user_id is not None:
        filters.append(EmailActionToken.user_id == user_id)
    if registration_request_id is not None:
        filters.append(EmailActionToken.registration_request_id == registration_request_id)
    db.execute(update(EmailActionToken).where(*filters).values(consumed_at=now))
    secret = make_email_action_token()
    token = EmailActionToken(
        id=uuid.uuid4(),
        purpose=purpose,
        token_hash=digest_secret(secret),
        user_id=user_id,
        registration_request_id=registration_request_id,
        pending_email=pending_email,
        expires_at=now + ACTION_TOKEN_LIFETIMES[purpose],
        created_at=now,
    )
    db.add(token)
    return token, secret


def effective_api_base_url(db: Session, settings: Settings) -> str:
    saved = db.get(SystemSetting, 1)
    if saved is not None and saved.api_base_url:
        return saved.api_base_url.rstrip("/")
    return settings.public_base_url.rstrip("/")


def action_url(db: Session, settings: Settings, path: str, secret: str) -> str:
    base = effective_api_base_url(db, settings)
    return f"{base}{path}?{urlencode({'token': secret})}"


def active_admin_emails(db: Session) -> list[str]:
    return list(
        db.scalars(
            select(User.email)
            .where(
                User.role == "admin",
                User.status == "active",
                User.email.is_not(None),
                User.email_verified_at.is_not(None),
            )
            .order_by(User.username)
        )
    )


def enqueue_admin_notice(
    db: Session,
    *,
    idempotency_key: str,
    template: str,
    payload: dict[str, object],
) -> None:
    addresses = active_admin_emails(db)
    if not addresses:
        return
    enqueue_notification(
        db,
        idempotency_key=idempotency_key,
        template=template,
        to_address=addresses[0],
        cc_addresses=addresses[1:],
        payload=payload,
    )

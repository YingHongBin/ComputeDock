from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..auditing import record_audit
from ..auth import AuthContext, require_admin, require_admin_csrf
from ..config import Settings, get_settings
from ..database import get_db
from ..models import (
    AdminSession,
    ComputeRequest,
    ComputeRequestChange,
    RegistrationRequest,
    User,
)
from ..notifications import action_url, enqueue_notification, issue_action_token
from ..schemas import (
    RegistrationRequestView,
    ReviewInput,
    UserAdminUpdate,
    UserView,
)
from ..security import utcnow

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        email_verified_at=user.email_verified_at,
        role=user.role,  # type: ignore[arg-type]
        status=user.status,  # type: ignore[arg-type]
        must_bind_email=user.must_bind_email,
        created_at=user.created_at,
    )


def registration_view(registration: RegistrationRequest) -> RegistrationRequestView:
    return RegistrationRequestView(
        id=registration.id,
        username=registration.username,
        full_name=registration.full_name,
        email=registration.email,
        status=registration.status,  # type: ignore[arg-type]
        email_verified_at=registration.email_verified_at,
        review_comment=registration.review_comment,
        reviewed_at=registration.reviewed_at,
        created_at=registration.created_at,
    )


@router.get("", response_model=list[UserView])
def list_users(
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[UserView]:
    users = list(db.scalars(select(User).order_by(User.created_at.desc())))
    return [user_view(user) for user in users]


@router.get("/registrations", response_model=list[RegistrationRequestView])
def list_registration_requests(
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[RegistrationRequestView]:
    registrations = list(
        db.scalars(
            select(RegistrationRequest)
            .where(RegistrationRequest.status != "email_pending")
            .order_by(RegistrationRequest.created_at.desc())
        )
    )
    return [registration_view(item) for item in registrations]


@router.post(
    "/registrations/{registration_id}/review",
    response_model=RegistrationRequestView,
)
def review_registration(
    registration_id: uuid.UUID,
    payload: ReviewInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> RegistrationRequestView:
    registration = db.scalar(
        select(RegistrationRequest)
        .where(RegistrationRequest.id == registration_id)
        .with_for_update()
    )
    if registration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "registration not found")
    if registration.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "registration is not pending")
    now = utcnow()
    if payload.decision == "approved":
        conflict = db.scalar(
            select(User.id).where(
                or_(
                    func.lower(User.username) == registration.username.lower(),
                    func.lower(User.email) == registration.email.lower(),
                )
            )
        )
        if conflict is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "username or email is unavailable")
        user = User(
            id=uuid.uuid4(),
            username=registration.username,
            full_name=registration.full_name,
            email=registration.email,
            email_verified_at=registration.email_verified_at,
            password_hash=registration.password_hash,
            role="user",
            status="active",
            must_bind_email=False,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        db.flush()
        registration.created_user_id = user.id
    registration.status = payload.decision
    registration.reviewer_id = auth.user.id
    registration.review_comment = payload.comment
    registration.reviewed_at = now
    registration.updated_at = now
    record_audit(
        db,
        auth.user,
        f"registration.{payload.decision}",
        "registration_request",
        registration.id,
        before={"status": "pending"},
        after={"status": payload.decision, "comment": payload.comment},
    )
    enqueue_notification(
        db,
        idempotency_key=f"registration-reviewed:{registration.id}",
        template=f"registration_{payload.decision}",
        to_address=registration.email,
        payload={
            "full_name": registration.full_name,
            "comment": payload.comment or "",
        },
    )
    db.commit()
    return registration_view(registration)


def auto_reject_user_requests(db: Session, user_id: uuid.UUID, reviewer_id: uuid.UUID) -> None:
    now = utcnow()
    reason = "关联用户已禁用"
    db.execute(
        update(ComputeRequest)
        .where(ComputeRequest.applicant_id == user_id, ComputeRequest.approval_status == "pending")
        .values(
            approval_status="rejected",
            reviewer_id=reviewer_id,
            review_comment=reason,
            reviewed_at=now,
            updated_at=now,
        )
    )
    db.execute(
        update(ComputeRequestChange)
        .where(
            ComputeRequestChange.requester_id == user_id,
            ComputeRequestChange.approval_status == "pending",
        )
        .values(
            approval_status="rejected",
            reviewer_id=reviewer_id,
            review_comment=reason,
            reviewed_at=now,
            updated_at=now,
        )
    )


@router.patch("/{user_id}", response_model=UserView)
def update_user(
    user_id: uuid.UUID,
    payload: UserAdminUpdate,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> UserView:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    next_role = payload.role or user.role
    next_status = payload.status or user.status
    if user.id == auth.user.id and (next_role != "admin" or next_status != "active"):
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot disable or demote yourself")
    losing_active_admin = (
        user.role == "admin"
        and user.status == "active"
        and (next_role != "admin" or next_status != "active")
    )
    if losing_active_admin:
        active_admins = db.scalar(
            select(func.count(User.id)).where(User.role == "admin", User.status == "active")
        )
        if int(active_admins or 0) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "cannot remove the last administrator")
    before = {"role": user.role, "status": user.status}
    user.role = next_role
    user.status = next_status
    user.updated_at = utcnow()
    if before["status"] != "disabled" and user.status == "disabled":
        auto_reject_user_requests(db, user.id, auth.user.id)
    if before != {"role": user.role, "status": user.status}:
        db.execute(
            delete(AdminSession).where(
                or_(AdminSession.user_id == user.id, AdminSession.admin_id == user.id)
            )
        )
    record_audit(
        db,
        auth.user,
        "user.update",
        "user",
        user.id,
        before=before,
        after={"role": user.role, "status": user.status},
    )
    db.commit()
    return user_view(user)


@router.post("/{user_id}/password-reset", status_code=status.HTTP_204_NO_CONTENT)
def trigger_password_reset(
    user_id: uuid.UUID,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if not user.email or user.email_verified_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "user has no verified email")
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
    record_audit(
        db,
        auth.user,
        "user.password_reset_requested",
        "user",
        user.id,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

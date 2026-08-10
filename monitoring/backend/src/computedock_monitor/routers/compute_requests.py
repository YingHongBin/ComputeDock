from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auditing import record_audit
from ..auth import AuthContext, require_admin_csrf, require_user, require_user_csrf
from ..database import get_db
from ..models import (
    ComputeRequest,
    ComputeRequestChange,
    ComputeResource,
    ContainerInstance,
    Project,
    ProjectMember,
    User,
)
from ..notifications import enqueue_admin_notice, enqueue_notification
from ..schemas import (
    ComputeRequestChangeInput,
    ComputeRequestChangeView,
    ComputeRequestInput,
    ComputeRequestView,
    ReviewInput,
)
from ..security import as_utc, digest_secret, make_compute_request_token, utcnow

router = APIRouter(prefix="/api/v1/compute-requests", tags=["compute-requests"])


def is_project_member(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return db.scalar(
        select(ProjectMember.project_id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ) is not None


def request_relations(
    db: Session, request: ComputeRequest
) -> tuple[User, Project, ComputeResource]:
    applicant = db.get(User, request.applicant_id)
    project = db.get(Project, request.project_id)
    resource = db.get(ComputeResource, request.resource_id)
    if applicant is None or project is None or resource is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "request relation is missing")
    return applicant, project, resource


def validate_request_relations(
    db: Session,
    applicant: User,
    project: Project,
    resource: ComputeResource,
) -> None:
    if applicant.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "applicant is disabled")
    if project.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "project is disabled")
    if resource.disabled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "resource is disabled")
    if not is_project_member(db, project.id, applicant.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "applicant is not a project member")


def actual_gpu_count(db: Session, request_id: uuid.UUID) -> int:
    containers = list(
        db.scalars(
            select(ContainerInstance).where(
                ContainerInstance.compute_request_id == request_id,
                ContainerInstance.removed_at.is_(None),
            )
        )
    )
    return len({gpuid for container in containers for gpuid in container.current_gpu_ids})


def runtime_status(request: ComputeRequest) -> str | None:
    if request.approval_status != "approved":
        return None
    if request.started_at is None or request.expires_at is None:
        return "not_started"
    now = utcnow()
    expires_at = as_utc(request.expires_at)
    if expires_at <= now:
        return "expired"
    if expires_at <= now + timedelta(days=1):
        return "expiring"
    return "running"


def reviewer_name(db: Session, reviewer_id: uuid.UUID | None) -> str | None:
    if reviewer_id is None:
        return None
    reviewer = db.get(User, reviewer_id)
    return reviewer.full_name if reviewer else None


def change_view(db: Session, change: ComputeRequestChange) -> ComputeRequestChangeView:
    return ComputeRequestChangeView(
        id=change.id,
        change_type=change.change_type,  # type: ignore[arg-type]
        amount=change.amount,
        approval_status=change.approval_status,  # type: ignore[arg-type]
        before_value=change.before_value,
        after_value=change.after_value,
        reviewer_name=reviewer_name(db, change.reviewer_id),
        review_comment=change.review_comment,
        reviewed_at=change.reviewed_at,
        created_at=change.created_at,
    )


def request_view(db: Session, request: ComputeRequest, *, include_token: bool) -> ComputeRequestView:
    applicant, project, resource = request_relations(db, request)
    actual = actual_gpu_count(db, request.id)
    changes = list(
        db.scalars(
            select(ComputeRequestChange)
            .where(ComputeRequestChange.request_id == request.id)
            .order_by(ComputeRequestChange.created_at.desc())
        )
    )
    return ComputeRequestView(
        id=request.id,
        applicant_id=applicant.id,
        applicant_username=applicant.username,
        applicant_name=applicant.full_name,
        project_id=project.id,
        project_name=project.name,
        resource_id=resource.id,
        resource_name=resource.name,
        gpu_count=request.gpu_count,
        duration_days=request.duration_days,
        approval_status=request.approval_status,  # type: ignore[arg-type]
        runtime_status=runtime_status(request),  # type: ignore[arg-type]
        actual_gpu_count=actual,
        over_quota=actual > request.gpu_count,
        reviewer_name=reviewer_name(db, request.reviewer_id),
        review_comment=request.review_comment,
        reviewed_at=request.reviewed_at,
        token=request.token if include_token and request.approval_status == "approved" else None,
        started_at=request.started_at,
        expires_at=request.expires_at,
        created_at=request.created_at,
        changes=[change_view(db, change) for change in changes],
    )


def visible_request(db: Session, request_id: uuid.UUID, auth: AuthContext) -> ComputeRequest:
    request = db.get(ComputeRequest, request_id)
    if request is None or (auth.user.role != "admin" and request.applicant_id != auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "compute request not found")
    return request


@router.get("", response_model=list[ComputeRequestView])
def list_compute_requests(
    applicant_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    approval_status: str | None = Query(default=None, pattern="^(pending|approved|rejected)$"),
    auth: AuthContext = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[ComputeRequestView]:
    query = select(ComputeRequest)
    if auth.user.role != "admin":
        query = query.where(ComputeRequest.applicant_id == auth.user.id)
    elif applicant_id is not None:
        query = query.where(ComputeRequest.applicant_id == applicant_id)
    if project_id is not None:
        query = query.where(ComputeRequest.project_id == project_id)
    if approval_status is not None:
        query = query.where(ComputeRequest.approval_status == approval_status)
    requests = list(db.scalars(query.order_by(ComputeRequest.created_at.desc())))
    return [
        request_view(db, request, include_token=auth.user.role == "admin")
        for request in requests
    ]


@router.post("", response_model=ComputeRequestView, status_code=status.HTTP_201_CREATED)
def create_compute_request(
    payload: ComputeRequestInput,
    auth: AuthContext = Depends(require_user_csrf),
    db: Session = Depends(get_db),
) -> ComputeRequestView:
    project = db.get(Project, payload.project_id)
    resource = db.get(ComputeResource, payload.resource_id)
    if project is None or resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project or resource not found")
    validate_request_relations(db, auth.user, project, resource)
    if payload.gpu_count > resource.gpu_count:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "requested GPUs exceed resource capacity",
        )
    now = utcnow()
    request = ComputeRequest(
        id=uuid.uuid4(),
        applicant_id=auth.user.id,
        project_id=project.id,
        resource_id=resource.id,
        gpu_count=payload.gpu_count,
        duration_days=payload.duration_days,
        approval_status="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(request)
    record_audit(
        db,
        auth.user,
        "compute_request.create",
        "compute_request",
        request.id,
        after={
            "project_id": str(project.id),
            "resource_id": str(resource.id),
            "gpu_count": request.gpu_count,
            "duration_days": request.duration_days,
        },
    )
    enqueue_admin_notice(
        db,
        idempotency_key=f"compute-request-pending:{request.id}",
        template="compute_request_pending_admin",
        payload={
            "applicant_name": auth.user.full_name,
            "project_name": project.name,
            "resource_name": resource.name,
            "gpu_count": request.gpu_count,
            "duration_days": request.duration_days,
        },
    )
    db.commit()
    return request_view(db, request, include_token=auth.user.role == "admin")


@router.get("/{request_id}", response_model=ComputeRequestView)
def get_compute_request(
    request_id: uuid.UUID,
    auth: AuthContext = Depends(require_user),
    db: Session = Depends(get_db),
) -> ComputeRequestView:
    request = visible_request(db, request_id, auth)
    return request_view(db, request, include_token=auth.user.role == "admin")


def notify_review_result(
    db: Session,
    applicant: User,
    *,
    object_id: uuid.UUID,
    template_prefix: str,
    decision: str,
    comment: str | None,
) -> None:
    if not applicant.email or applicant.email_verified_at is None:
        return
    enqueue_notification(
        db,
        idempotency_key=f"{template_prefix}-reviewed:{object_id}",
        template=f"{template_prefix}_{decision}",
        to_address=applicant.email,
        payload={"full_name": applicant.full_name, "comment": comment or ""},
    )


@router.post("/{request_id}/review", response_model=ComputeRequestView)
def review_compute_request(
    request_id: uuid.UUID,
    payload: ReviewInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ComputeRequestView:
    request = db.scalar(
        select(ComputeRequest).where(ComputeRequest.id == request_id).with_for_update()
    )
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "compute request not found")
    if request.approval_status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "compute request is not pending")
    applicant, project, resource = request_relations(db, request)
    now = utcnow()
    if payload.decision == "approved":
        validate_request_relations(db, applicant, project, resource)
        if request.gpu_count > resource.gpu_count:
            raise HTTPException(status.HTTP_409_CONFLICT, "requested GPUs exceed resource capacity")
        secret = make_compute_request_token()
        request.token = secret
        request.token_hash = digest_secret(secret)
    request.approval_status = payload.decision
    request.reviewer_id = auth.user.id
    request.review_comment = payload.comment
    request.reviewed_at = now
    request.updated_at = now
    record_audit(
        db,
        auth.user,
        f"compute_request.{payload.decision}",
        "compute_request",
        request.id,
        before={"approval_status": "pending"},
        after={"approval_status": payload.decision, "comment": payload.comment},
    )
    notify_review_result(
        db,
        applicant,
        object_id=request.id,
        template_prefix="compute_request",
        decision=payload.decision,
        comment=payload.comment,
    )
    db.commit()
    return request_view(db, request, include_token=True)


def change_values(request: ComputeRequest, payload: ComputeRequestChangeInput) -> tuple[int, int]:
    if payload.change_type == "extend":
        return request.duration_days, request.duration_days + payload.amount
    if payload.change_type == "expand":
        return request.gpu_count, request.gpu_count + payload.amount
    return request.gpu_count, request.gpu_count - payload.amount


@router.post(
    "/{request_id}/changes",
    response_model=ComputeRequestChangeView,
    status_code=status.HTTP_201_CREATED,
)
def create_compute_request_change(
    request_id: uuid.UUID,
    payload: ComputeRequestChangeInput,
    auth: AuthContext = Depends(require_user_csrf),
    db: Session = Depends(get_db),
) -> ComputeRequestChangeView:
    request = db.scalar(
        select(ComputeRequest).where(ComputeRequest.id == request_id).with_for_update()
    )
    if request is None or request.applicant_id != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "compute request not found")
    if request.approval_status != "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "compute request is not approved")
    if request.started_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "compute request has not started reporting",
        )
    if request.expires_at is not None and as_utc(request.expires_at) <= utcnow():
        raise HTTPException(status.HTTP_409_CONFLICT, "compute request has expired")
    applicant, project, resource = request_relations(db, request)
    validate_request_relations(db, applicant, project, resource)
    existing = db.scalar(
        select(ComputeRequestChange.id).where(
            ComputeRequestChange.request_id == request.id,
            ComputeRequestChange.approval_status == "pending",
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a change request is already pending")
    before_value, after_value = change_values(request, payload)
    if payload.change_type == "release" and after_value < 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "at least one GPU is required")
    if payload.change_type == "expand" and after_value > resource.gpu_count:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "expanded GPUs exceed resource capacity",
        )
    now = utcnow()
    change = ComputeRequestChange(
        id=uuid.uuid4(),
        request_id=request.id,
        requester_id=auth.user.id,
        change_type=payload.change_type,
        amount=payload.amount,
        approval_status="pending",
        before_value=before_value,
        after_value=after_value,
        created_at=now,
        updated_at=now,
    )
    db.add(change)
    enqueue_admin_notice(
        db,
        idempotency_key=f"compute-change-pending:{change.id}",
        template="compute_change_pending_admin",
        payload={
            "applicant_name": applicant.full_name,
            "change_type": change.change_type,
            "amount": change.amount,
        },
    )
    record_audit(
        db,
        auth.user,
        "compute_change.create",
        "compute_request_change",
        change.id,
        after={"type": change.change_type, "amount": change.amount},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "a change request is already pending") from exc
    return change_view(db, change)


def reject_expired_change(
    db: Session,
    request: ComputeRequest,
    change: ComputeRequestChange,
    reviewer: User,
) -> None:
    now = utcnow()
    change.approval_status = "rejected"
    change.reviewer_id = reviewer.id
    change.review_comment = "原申请已到期"
    change.reviewed_at = now
    change.updated_at = now
    applicant = db.get(User, request.applicant_id)
    if applicant:
        notify_review_result(
            db,
            applicant,
            object_id=change.id,
            template_prefix="compute_change",
            decision="rejected",
            comment=change.review_comment,
        )


@router.post("/{request_id}/changes/{change_id}/review", response_model=ComputeRequestChangeView)
def review_compute_request_change(
    request_id: uuid.UUID,
    change_id: uuid.UUID,
    payload: ReviewInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ComputeRequestChangeView:
    request = db.scalar(
        select(ComputeRequest).where(ComputeRequest.id == request_id).with_for_update()
    )
    change = db.scalar(
        select(ComputeRequestChange)
        .where(
            ComputeRequestChange.id == change_id,
            ComputeRequestChange.request_id == request_id,
        )
        .with_for_update()
    )
    if request is None or change is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "change request not found")
    if change.approval_status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "change request is not pending")
    if request.expires_at is not None and as_utc(request.expires_at) <= utcnow():
        reject_expired_change(db, request, change, auth.user)
        db.commit()
        return change_view(db, change)
    applicant, project, resource = request_relations(db, request)
    now = utcnow()
    if payload.decision == "approved":
        validate_request_relations(db, applicant, project, resource)
        if change.change_type == "expand" and change.after_value > resource.gpu_count:
            raise HTTPException(status.HTTP_409_CONFLICT, "expanded GPUs exceed resource capacity")
        if change.change_type == "extend":
            request.duration_days = change.after_value
            if request.expires_at is not None:
                request.expires_at = as_utc(request.expires_at) + timedelta(days=change.amount)
        else:
            request.gpu_count = change.after_value
        request.updated_at = now
    change.approval_status = payload.decision
    change.reviewer_id = auth.user.id
    change.review_comment = payload.comment
    change.reviewed_at = now
    change.updated_at = now
    record_audit(
        db,
        auth.user,
        f"compute_change.{payload.decision}",
        "compute_request_change",
        change.id,
        before={"approval_status": "pending"},
        after={
            "approval_status": payload.decision,
            "before_value": change.before_value,
            "after_value": change.after_value,
            "comment": payload.comment,
        },
    )
    notify_review_result(
        db,
        applicant,
        object_id=change.id,
        template_prefix="compute_change",
        decision=payload.decision,
        comment=payload.comment,
    )
    db.commit()
    return change_view(db, change)

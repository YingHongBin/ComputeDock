from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auditing import record_audit
from ..auth import AuthContext, require_admin_csrf, require_user
from ..config import Settings, get_settings
from ..database import get_db
from ..models import ComputeRequest, ComputeRequestChange, ComputeResource, ContainerInstance
from ..schemas import (
    ChartResponse,
    ContainerSummary,
    ResourceCard,
    ResourceDetail,
    ResourceInput,
)
from ..security import utcnow
from ..services import chart_data, container_summaries, resource_card

router = APIRouter(prefix="/api/v1/resources", tags=["resources"])


def resource_record(db: Session, resource_id: uuid.UUID) -> ComputeResource:
    resource = db.get(ComputeResource, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    return resource


def card_for(db: Session, resource: ComputeResource, *, include_token: bool) -> ResourceCard:
    containers = list(
        db.scalars(
            select(ContainerInstance).where(
                ContainerInstance.resource_id == resource.id,
                ContainerInstance.removed_at.is_(None),
            )
        )
    )
    return resource_card(resource, containers, include_token=include_token)


@router.get("", response_model=list[ResourceCard])
def list_resources(
    auth: AuthContext = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[ResourceCard]:
    resources = list(
        db.scalars(
            select(ComputeResource).order_by(ComputeResource.created_at.desc())
        )
    )
    containers = list(
        db.scalars(select(ContainerInstance).where(ContainerInstance.removed_at.is_(None)))
    )
    by_resource: dict[uuid.UUID, list[ContainerInstance]] = {}
    for container in containers:
        by_resource.setdefault(container.resource_id, []).append(container)
    return [
        resource_card(
            item,
            by_resource.get(item.id, []),
            include_token=auth.user.role == "admin",
        )
        for item in resources
    ]


@router.post("", response_model=ResourceDetail, status_code=status.HTTP_201_CREATED)
def create_resource(
    payload: ResourceInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ResourceDetail:
    now = utcnow()
    resource = ComputeResource(
        id=uuid.uuid4(),
        name=payload.name,
        gpu_model=payload.gpu_model,
        gpu_count=payload.gpu_count,
        token_hash=None,
        token=None,
        created_at=now,
        updated_at=now,
    )
    db.add(resource)
    record_audit(
        db,
        auth.user,
        "resource.create",
        "compute_resource",
        resource.id,
        after={
            "name": resource.name,
            "gpu_model": resource.gpu_model,
            "gpu_count": resource.gpu_count,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "resource name already exists") from exc
    card = resource_card(resource, [])
    return ResourceDetail(**card.model_dump(), created_at=resource.created_at)


@router.get("/{resource_id}", response_model=ResourceDetail)
def get_resource(
    resource_id: uuid.UUID,
    auth: AuthContext = Depends(require_user),
    db: Session = Depends(get_db),
) -> ResourceDetail:
    resource = resource_record(db, resource_id)
    card = card_for(db, resource, include_token=auth.user.role == "admin")
    return ResourceDetail(**card.model_dump(), created_at=resource.created_at)


@router.put("/{resource_id}", response_model=ResourceDetail)
def update_resource(
    resource_id: uuid.UUID,
    payload: ResourceInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ResourceDetail:
    resource = resource_record(db, resource_id)
    before = {
        "name": resource.name,
        "gpu_model": resource.gpu_model,
        "gpu_count": resource.gpu_count,
    }
    resource.name = payload.name
    resource.gpu_model = payload.gpu_model
    resource.gpu_count = payload.gpu_count
    resource.updated_at = utcnow()
    record_audit(
        db,
        auth.user,
        "resource.update",
        "compute_resource",
        resource.id,
        before=before,
        after={
            "name": resource.name,
            "gpu_model": resource.gpu_model,
            "gpu_count": resource.gpu_count,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "resource name already exists") from exc
    card = card_for(db, resource, include_token=True)
    return ResourceDetail(**card.model_dump(), created_at=resource.created_at)


def reject_pending_for_resource(
    db: Session, resource_id: uuid.UUID, reviewer_id: uuid.UUID
) -> None:
    now = utcnow()
    reason = "关联算力资源已禁用"
    request_ids = select(ComputeRequest.id).where(ComputeRequest.resource_id == resource_id)
    db.execute(
        update(ComputeRequest)
        .where(
            ComputeRequest.resource_id == resource_id,
            ComputeRequest.approval_status == "pending",
        )
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
            ComputeRequestChange.request_id.in_(request_ids),
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


def set_resource_status(
    resource_id: uuid.UUID,
    disabled: bool,
    auth: AuthContext,
    db: Session,
) -> ResourceDetail:
    resource = db.scalar(
        select(ComputeResource).where(ComputeResource.id == resource_id).with_for_update()
    )
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    before = "disabled" if resource.disabled_at is not None else "active"
    now = utcnow()
    resource.disabled_at = now if disabled else None
    resource.disabled_by_id = auth.user.id if disabled else None
    resource.updated_at = now
    target = "disabled" if disabled else "active"
    if before != "disabled" and disabled:
        reject_pending_for_resource(db, resource.id, auth.user.id)
    record_audit(
        db,
        auth.user,
        f"resource.{target}",
        "compute_resource",
        resource.id,
        before={"status": before},
        after={"status": target},
    )
    db.commit()
    card = card_for(db, resource, include_token=True)
    return ResourceDetail(**card.model_dump(), created_at=resource.created_at)


@router.post("/{resource_id}/disable", response_model=ResourceDetail)
def disable_resource(
    resource_id: uuid.UUID,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ResourceDetail:
    return set_resource_status(resource_id, True, auth, db)


@router.post("/{resource_id}/enable", response_model=ResourceDetail)
def enable_resource(
    resource_id: uuid.UUID,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ResourceDetail:
    return set_resource_status(resource_id, False, auth, db)


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT, deprecated=True)
def legacy_disable_resource(
    resource_id: uuid.UUID,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> Response:
    set_resource_status(resource_id, True, auth, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{resource_id}/containers", response_model=list[ContainerSummary])
def list_containers(
    resource_id: uuid.UUID,
    _auth: AuthContext = Depends(require_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[ContainerSummary]:
    resource_record(db, resource_id)
    return container_summaries(db, resource_id, settings.offline_seconds)


@router.delete("/{resource_id}/containers/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_container(
    resource_id: uuid.UUID,
    container_id: uuid.UUID,
    _auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> Response:
    resource_record(db, resource_id)
    container = db.scalar(
        select(ContainerInstance).where(
            ContainerInstance.id == container_id,
            ContainerInstance.resource_id == resource_id,
            ContainerInstance.removed_at.is_(None),
        )
    )
    if container is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "container not found")
    container.removed_at = utcnow()
    record_audit(
        db,
        _auth.user,
        "container.remove",
        "container_instance",
        container.id,
        after={"removed_at": container.removed_at.isoformat()},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{resource_id}/containers/{container_id}/chart", response_model=ChartResponse)
def get_chart(
    resource_id: uuid.UUID,
    container_id: uuid.UUID,
    range_name: str = Query(default="7d", alias="range", pattern="^(1h|6h|1d|7d)$"),
    _auth: AuthContext = Depends(require_user),
    db: Session = Depends(get_db),
) -> ChartResponse:
    resource_record(db, resource_id)
    container = db.scalar(
        select(ContainerInstance).where(
            ContainerInstance.id == container_id,
            ContainerInstance.resource_id == resource_id,
            ContainerInstance.removed_at.is_(None),
        )
    )
    if container is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "container not found")
    return chart_data(db, resource_id, container, range_name)

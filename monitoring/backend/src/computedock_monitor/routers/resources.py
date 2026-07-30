from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import AuthContext, require_admin, require_csrf
from ..config import Settings, get_settings
from ..database import get_db
from ..models import ComputeResource, ContainerInstance
from ..schemas import (
    ChartResponse,
    ContainerSummary,
    ResourceCard,
    ResourceDetail,
    ResourceInput,
)
from ..security import digest_secret, make_resource_token, utcnow
from ..services import chart_data, container_summaries, resource_card

router = APIRouter(prefix="/api/v1/resources", tags=["resources"])


def active_resource(db: Session, resource_id: uuid.UUID) -> ComputeResource:
    resource = db.scalar(
        select(ComputeResource).where(
            ComputeResource.id == resource_id,
            ComputeResource.archived_at.is_(None),
        )
    )
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    return resource


def card_for(db: Session, resource: ComputeResource) -> ResourceCard:
    containers = list(
        db.scalars(
            select(ContainerInstance).where(
                ContainerInstance.resource_id == resource.id,
                ContainerInstance.removed_at.is_(None),
            )
        )
    )
    return resource_card(resource, containers)


@router.get("", response_model=list[ResourceCard])
def list_resources(
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[ResourceCard]:
    resources = list(
        db.scalars(
            select(ComputeResource)
            .where(ComputeResource.archived_at.is_(None))
            .order_by(ComputeResource.created_at.desc())
        )
    )
    containers = list(
        db.scalars(select(ContainerInstance).where(ContainerInstance.removed_at.is_(None)))
    )
    by_resource: dict[uuid.UUID, list[ContainerInstance]] = {}
    for container in containers:
        by_resource.setdefault(container.resource_id, []).append(container)
    return [resource_card(item, by_resource.get(item.id, [])) for item in resources]


@router.post("", response_model=ResourceDetail, status_code=status.HTTP_201_CREATED)
def create_resource(
    payload: ResourceInput,
    _auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ResourceDetail:
    now = utcnow()
    token = make_resource_token()
    resource = ComputeResource(
        id=uuid.uuid4(),
        name=payload.name,
        gpu_model=payload.gpu_model,
        gpu_count=payload.gpu_count,
        token_hash=digest_secret(token),
        token=token,
        created_at=now,
        updated_at=now,
    )
    db.add(resource)
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
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ResourceDetail:
    resource = active_resource(db, resource_id)
    card = card_for(db, resource)
    return ResourceDetail(**card.model_dump(), created_at=resource.created_at)


@router.put("/{resource_id}", response_model=ResourceDetail)
def update_resource(
    resource_id: uuid.UUID,
    payload: ResourceInput,
    _auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ResourceDetail:
    resource = active_resource(db, resource_id)
    resource.name = payload.name
    resource.gpu_model = payload.gpu_model
    resource.gpu_count = payload.gpu_count
    resource.updated_at = utcnow()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "resource name already exists") from exc
    card = card_for(db, resource)
    return ResourceDetail(**card.model_dump(), created_at=resource.created_at)


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_resource(
    resource_id: uuid.UUID,
    _auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    resource = active_resource(db, resource_id)
    resource.archived_at = utcnow()
    resource.updated_at = resource.archived_at
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{resource_id}/containers", response_model=list[ContainerSummary])
def list_containers(
    resource_id: uuid.UUID,
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[ContainerSummary]:
    active_resource(db, resource_id)
    return container_summaries(db, resource_id, settings.offline_seconds)


@router.delete("/{resource_id}/containers/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_container(
    resource_id: uuid.UUID,
    container_id: uuid.UUID,
    _auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    active_resource(db, resource_id)
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
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{resource_id}/containers/{container_id}/chart", response_model=ChartResponse)
def get_chart(
    resource_id: uuid.UUID,
    container_id: uuid.UUID,
    range_name: str = Query(default="7d", alias="range", pattern="^(1h|6h|1d|7d)$"),
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ChartResponse:
    active_resource(db, resource_id)
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

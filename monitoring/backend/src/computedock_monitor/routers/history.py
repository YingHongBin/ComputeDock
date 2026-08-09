from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import AuthContext, require_admin
from ..config import Settings, get_settings
from ..database import get_db
from ..models import (
    ComputeRequest,
    ComputeResource,
    ContainerInstance,
    HourlyGpuRollup,
    Project,
    User,
)
from ..schemas import (
    HistoryContainerChart,
    HistoryContainerView,
    HourlyHistoryPoint,
    HourlyHistorySeries,
)
from ..security import as_utc, utcnow

router = APIRouter(prefix="/api/v1/history", tags=["history"])


@router.get("/containers", response_model=list[HistoryContainerView])
def list_history_containers(
    user_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    resource_id: uuid.UUID | None = Query(default=None),
    container_status: str | None = Query(default=None, pattern="^(online|offline|removed)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[HistoryContainerView]:
    if user_id is None and project_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "user_id or project_id is required",
        )
    query = (
        select(ContainerInstance, ComputeRequest, User, Project, ComputeResource)
        .join(ComputeRequest, ComputeRequest.id == ContainerInstance.compute_request_id)
        .join(User, User.id == ComputeRequest.applicant_id)
        .join(Project, Project.id == ComputeRequest.project_id)
        .join(ComputeResource, ComputeResource.id == ContainerInstance.resource_id)
    )
    if user_id is not None:
        query = query.where(ComputeRequest.applicant_id == user_id)
    if project_id is not None:
        query = query.where(ComputeRequest.project_id == project_id)
    if resource_id is not None:
        query = query.where(ContainerInstance.resource_id == resource_id)
    if container_status == "removed":
        query = query.where(ContainerInstance.removed_at.is_not(None))
    elif container_status in ("online", "offline"):
        query = query.where(ContainerInstance.removed_at.is_(None))
    rows = db.execute(
        query.order_by(ContainerInstance.last_received_at.desc()).limit(limit).offset(offset)
    )
    threshold = utcnow() - timedelta(seconds=settings.offline_seconds)
    result: list[HistoryContainerView] = []
    for container, request, applicant, project, resource in rows:
        if container.removed_at is not None:
            current_status = "removed"
        else:
            current_status = (
                "online" if as_utc(container.last_received_at) >= threshold else "offline"
            )
        if container_status and current_status != container_status:
            continue
        result.append(
            HistoryContainerView(
                id=container.id,
                name=container.name,
                generation=container.generation,
                status=current_status,  # type: ignore[arg-type]
                applicant_id=applicant.id,
                applicant_name=applicant.full_name,
                project_id=project.id,
                project_name=project.name,
                resource_id=resource.id,
                resource_name=resource.name,
                compute_request_id=request.id,
                first_reported_at=container.first_reported_at,
                last_received_at=container.last_received_at,
                removed_at=container.removed_at,
                expires_at=request.expires_at,
            )
        )
    return result


@router.get("/containers/{container_id}/chart", response_model=HistoryContainerChart)
def history_container_chart(
    container_id: uuid.UUID,
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HistoryContainerChart:
    container = db.get(ContainerInstance, container_id)
    if (
        container is None
        or container.compute_request_id is None
        or container.removed_at is None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "historical container not found")
    rollups = list(
        db.scalars(
            select(HourlyGpuRollup)
            .where(HourlyGpuRollup.container_id == container.id)
            .order_by(HourlyGpuRollup.gpuid, HourlyGpuRollup.bucket_start)
        )
    )
    by_gpu: dict[str, list[HourlyHistoryPoint]] = {}
    for item in rollups:
        by_gpu.setdefault(item.gpuid, []).append(
            HourlyHistoryPoint(
                time=item.bucket_start,
                utilization_avg=item.utilization_avg,
                utilization_max=item.utilization_max,
                memory_used_avg=item.memory_used_avg,
                memory_used_max=item.memory_used_max,
                memory_total=item.memory_total,
                online_seconds=item.online_seconds,
                sample_count=item.sample_count,
            )
        )
    return HistoryContainerChart(
        container_id=container.id,
        container_name=container.name,
        first_reported_at=container.first_reported_at,
        removed_at=container.removed_at,
        series=[
            HourlyHistorySeries(gpuid=gpuid, points=points)
            for gpuid, points in by_gpu.items()
        ],
    )

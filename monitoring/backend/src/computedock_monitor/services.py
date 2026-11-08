from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    ComputeRequest,
    ComputeResource,
    ContainerInstance,
    GpuSample,
    Project,
    SampleBatch,
    User,
)
from .schemas import (
    ChartPoint,
    ChartResponse,
    ContainerSummary,
    GpuChartSeries,
    ResourceCard,
    SampleInput,
)
from .security import as_utc, digest_secret, utcnow

RANGES = {
    "1h": (timedelta(hours=1), 60),
    "6h": (timedelta(hours=6), 300),
    "1d": (timedelta(days=1), 900),
    "7d": (timedelta(days=7), 3600),
}


def aligned_chart_window(
    now: datetime, duration: timedelta, bucket_seconds: int
) -> tuple[datetime, datetime]:
    end_epoch = (int(now.timestamp()) // bucket_seconds + 1) * bucket_seconds
    end = datetime.fromtimestamp(end_epoch, UTC)
    return end - duration, end


def resource_card(
    resource: ComputeResource,
    containers: list[ContainerInstance],
    requests: Sequence[ComputeRequest] = (),
) -> ResourceCard:
    now = utcnow()
    active = [
        item
        for item in requests
        if item.approval_status == "approved"
        and (item.expires_at is None or as_utc(item.expires_at) > now)
    ]
    reserved = {
        key: sum(getattr(item, key) for item in active)
        for key in ("gpu_count", "cpu_cores", "memory_gib")
    }
    allocated = len(
        {
            gpuid
            for container in containers
            if container.removed_at is None
            for gpuid in container.current_gpu_ids
        }
    )
    return ResourceCard(
        id=resource.id,
        name=resource.name,
        description=resource.description or "",
        gpu_model=resource.gpu_model,
        gpu_count=resource.gpu_count,
        cpu_cores=resource.cpu_cores,
        memory_gib=resource.memory_gib,
        default_cpu_cores=resource.default_cpu_cores,
        default_memory_gib=resource.default_memory_gib,
        **{f"reserved_{key}": value for key, value in reserved.items()},
        **{
            f"remaining_{key}": max(getattr(resource, key) - value, 0)
            for key, value in reserved.items()
        },
        allocated_gpu_count=allocated,
        available_gpu_count=max(resource.gpu_count - allocated, 0),
        overallocated=allocated > resource.gpu_count,
        status="disabled" if resource.disabled_at is not None else "active",
    )


def canonical_payload_hash(payload: SampleInput) -> bytes:
    content = {
        "container_name": payload.container_name,
        "collected_at": payload.collected_at.isoformat(),
        "gpus": sorted([gpu.model_dump() for gpu in payload.gpus], key=lambda item: item["gpuid"]),
    }
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).digest()


def validate_collection_time(collected_at: datetime, now: datetime) -> datetime:
    if collected_at.tzinfo is None or collected_at.utcoffset() is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "collected_at needs timezone")
    normalized = collected_at.astimezone(UTC)
    if normalized > now + timedelta(minutes=5):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "collected_at is in future")
    if normalized < now - timedelta(hours=24):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "collected_at is too old")
    return normalized


def authenticate_reporting_token(db: Session, token: str) -> tuple[ComputeResource, ComputeRequest]:
    token_hash = digest_secret(token)
    request = db.scalar(
        select(ComputeRequest).where(
            ComputeRequest.token_hash == token_hash,
            ComputeRequest.approval_status == "approved",
        )
    )
    if request is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid reporting token")
    resource = db.get(ComputeResource, request.resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid reporting token")
    return resource, request


def lock_resource_lifecycle(db: Session, resource_id: uuid.UUID) -> None:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:resource_id))"),
        {"resource_id": str(resource_id)},
    )


def start_compute_request(request: ComputeRequest, received_at: datetime) -> bool:
    if request.started_at is not None:
        return False
    request.started_at = received_at
    request.expires_at = received_at + timedelta(days=request.duration_days)
    request.updated_at = received_at
    return True


def get_or_create_container(
    db: Session,
    resource: ComputeResource,
    request: ComputeRequest,
    name: str,
    collected_at: datetime,
    received_at: datetime,
) -> ContainerInstance:
    namespace_filters = [ContainerInstance.compute_request_id == request.id]
    container = db.scalar(
        select(ContainerInstance)
        .where(
            *namespace_filters,
            ContainerInstance.name == name,
            ContainerInstance.removed_at.is_(None),
        )
        .with_for_update()
    )
    if container is not None:
        return container
    existing = db.scalar(
        select(ContainerInstance).where(
            ContainerInstance.compute_request_id == request.id,
            ContainerInstance.removed_at.is_(None),
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"request already has a container: {existing.name}"
        )
    generation = db.scalar(
        select(func.coalesce(func.max(ContainerInstance.generation), 0)).where(
            *namespace_filters,
            ContainerInstance.name == name,
        )
    )
    container = ContainerInstance(
        id=uuid.uuid4(),
        resource_id=resource.id,
        compute_request_id=request.id,
        name=name,
        generation=int(generation or 0) + 1,
        first_reported_at=collected_at,
        last_received_at=received_at,
        latest_collected_at=collected_at,
        current_gpu_ids=[],
    )
    db.add(container)
    db.flush()
    return container


def ingest_sample(
    db: Session,
    resource: ComputeResource,
    payload: SampleInput,
    request: ComputeRequest,
) -> tuple[str, ContainerInstance]:
    received_at = utcnow()
    collected_at = validate_collection_time(payload.collected_at, received_at)
    payload = payload.model_copy(update={"collected_at": collected_at})
    lock_resource_lifecycle(db, resource.id)
    db.refresh(resource)
    db.refresh(request)
    start_compute_request(request, received_at)
    container = get_or_create_container(
        db, resource, request, payload.container_name, collected_at, received_at
    )
    payload_hash = canonical_payload_hash(payload)
    existing = db.scalar(
        select(SampleBatch).where(
            SampleBatch.container_id == container.id,
            SampleBatch.collected_at == collected_at,
        )
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "different payload already exists for collected_at",
            )
        container.last_received_at = max(as_utc(container.last_received_at), received_at)
        db.commit()
        return "duplicate", container

    batch = SampleBatch(
        id=uuid.uuid4(),
        container_id=container.id,
        collected_at=collected_at,
        received_at=received_at,
        payload_hash=payload_hash,
    )
    db.add(batch)
    for gpu in payload.gpus:
        db.add(
            GpuSample(
                collected_at=collected_at,
                received_at=received_at,
                batch_id=batch.id,
                resource_id=resource.id,
                container_id=container.id,
                gpuid=gpu.gpuid,
                memory_used=gpu.memory_used,
                memory_total=gpu.memory_total,
                utilization=gpu.utilization,
            )
        )
    container.last_received_at = max(as_utc(container.last_received_at), received_at)
    container.first_reported_at = min(as_utc(container.first_reported_at), collected_at)
    if collected_at >= as_utc(container.latest_collected_at):
        container.latest_collected_at = collected_at
        container.current_gpu_ids = sorted(gpu.gpuid for gpu in payload.gpus)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        namespace_filters = [ContainerInstance.compute_request_id == request.id]
        concurrent_container = db.scalar(
            select(ContainerInstance).where(
                *namespace_filters,
                ContainerInstance.name == payload.container_name,
                ContainerInstance.removed_at.is_(None),
            )
        )
        if concurrent_container is not None:
            existing = db.scalar(
                select(SampleBatch).where(
                    SampleBatch.container_id == concurrent_container.id,
                    SampleBatch.collected_at == collected_at,
                )
            )
            if existing is not None and existing.payload_hash == payload_hash:
                return "duplicate", concurrent_container
            if existing is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "different payload already exists for collected_at",
                ) from exc
        raise
    return "accepted", container


def container_summaries(
    db: Session,
    resource_id: uuid.UUID,
    offline_seconds: int,
) -> list[ContainerSummary]:
    container_rows = list(
        db.execute(
            select(ContainerInstance, ComputeRequest.expires_at)
            .join(ComputeRequest, ComputeRequest.id == ContainerInstance.compute_request_id)
            .where(
                ContainerInstance.resource_id == resource_id,
                ContainerInstance.removed_at.is_(None),
            )
            .order_by(
                ComputeRequest.expires_at.asc().nulls_last(),
                ContainerInstance.last_received_at.desc(),
            )
        )
    )
    if not container_rows:
        return []
    rows = db.execute(
        text(
            """
            WITH per_collection AS (
                SELECT container_id, collected_at, AVG(utilization)::float AS utilization
                FROM gpu_samples
                WHERE resource_id = :resource_id
                  AND collected_at >= :since
                GROUP BY container_id, collected_at
            )
            SELECT container_id,
                AVG(utilization) FILTER (WHERE collected_at >= :one_hour) AS utilization_1h,
                AVG(utilization) FILTER (WHERE collected_at >= :six_hours) AS utilization_6h,
                AVG(utilization) FILTER (WHERE collected_at >= :one_day) AS utilization_1d,
                AVG(utilization) AS utilization_7d
            FROM per_collection
            GROUP BY container_id
            """
        ),
        {
            "resource_id": resource_id,
            "since": utcnow() - timedelta(days=7),
            "one_hour": utcnow() - timedelta(hours=1),
            "six_hours": utcnow() - timedelta(hours=6),
            "one_day": utcnow() - timedelta(days=1),
        },
    )
    usage = {row.container_id: row for row in rows}
    threshold = utcnow() - timedelta(seconds=offline_seconds)
    result: list[ContainerSummary] = []
    for container, expires_at in container_rows:
        project_name, applicant_name = container_context(db, container)
        result.append(
            ContainerSummary(
                id=container.id,
                name=container.name,
                project_name=project_name,
                applicant_name=applicant_name,
                generation=container.generation,
                status="online" if container.last_received_at >= threshold else "offline",
                last_received_at=container.last_received_at,
                expires_at=expires_at,
                allocated_gpu_count=len(container.current_gpu_ids),
                utilization_1h=_rounded(getattr(usage.get(container.id), "utilization_1h", None)),
                utilization_6h=_rounded(getattr(usage.get(container.id), "utilization_6h", None)),
                utilization_1d=_rounded(getattr(usage.get(container.id), "utilization_1d", None)),
                utilization_7d=_rounded(getattr(usage.get(container.id), "utilization_7d", None)),
            )
        )
    return result


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def container_context(db: Session, container: ContainerInstance) -> tuple[str, str]:
    request = db.get(ComputeRequest, container.compute_request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "compute request not found")
    project = db.get(Project, request.project_id)
    applicant = db.get(User, request.applicant_id)
    if project is None or applicant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "container context not found")
    return project.name, applicant.full_name


def chart_data(
    db: Session,
    resource_id: uuid.UUID,
    container: ContainerInstance,
    range_name: str,
) -> ChartResponse:
    if range_name not in RANGES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid chart range")
    duration, bucket_seconds = RANGES[range_name]
    project_name, applicant_name = container_context(db, container)
    start, end = aligned_chart_window(utcnow(), duration, bucket_seconds)
    gpu_ids = set(container.current_gpu_ids)
    gpu_ids.update(
        db.scalars(
            select(GpuSample.gpuid)
            .where(
                GpuSample.container_id == container.id,
                GpuSample.collected_at >= start,
                GpuSample.collected_at <= end,
            )
            .distinct()
        )
    )
    active_containers = list(
        db.scalars(
            select(ContainerInstance).where(
                ContainerInstance.resource_id == resource_id,
                ContainerInstance.removed_at.is_(None),
            )
        )
    )
    counts: dict[str, int] = {}
    for active in active_containers:
        for gpuid in active.current_gpu_ids:
            counts[gpuid] = counts.get(gpuid, 0) + 1

    series: list[GpuChartSeries] = []
    for gpuid in sorted(gpu_ids):
        first_last = db.execute(
            select(func.min(GpuSample.collected_at), func.max(GpuSample.collected_at)).where(
                GpuSample.container_id == container.id, GpuSample.gpuid == gpuid
            )
        ).one()
        if first_last[0] is None:
            continue
        rows = db.execute(
            text(
                """
                SELECT date_bin(
                           make_interval(secs => :bucket_seconds),
                           collected_at,
                           TIMESTAMPTZ '1970-01-01 00:00:00+00'
                       ) AS bucket,
                       AVG(memory_used)::float AS memory_used,
                       AVG(memory_total)::float AS memory_total,
                       AVG(utilization)::float AS utilization
                FROM gpu_samples
                WHERE container_id = :container_id
                  AND gpuid = :gpuid
                  AND collected_at >= :start
                  AND collected_at < :end
                GROUP BY 1
                ORDER BY 1
                """
            ),
            {
                "start": start,
                "end": end,
                "bucket_seconds": bucket_seconds,
                "container_id": container.id,
                "gpuid": gpuid,
            },
        )
        points = [
            ChartPoint(
                time=row.bucket,
                memory_used=_rounded(row.memory_used),
                memory_total=_rounded(row.memory_total),
                utilization=_rounded(row.utilization),
            )
            for row in rows
        ]
        series.append(
            GpuChartSeries(
                gpuid=gpuid,
                shared=counts.get(gpuid, 0) > 1,
                first_reported_at=first_last[0],
                last_reported_at=first_last[1],
                points=points,
            )
        )
    return ChartResponse(
        container_id=container.id,
        container_name=container.name,
        project_name=project_name,
        applicant_name=applicant_name,
        range=range_name,  # type: ignore[arg-type]
        bucket_seconds=bucket_seconds,
        window_start=start,
        window_end=end,
        instance_first_reported_at=container.first_reported_at,
        instance_removed_at=container.removed_at,
        series=series,
    )

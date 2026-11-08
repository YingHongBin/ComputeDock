from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import parse_bearer
from ..database import get_db
from ..models import ContainerInstance, Project, User
from ..schemas import AgentAllocation, SampleAccepted, SampleInput
from ..security import as_utc, utcnow
from ..services import authenticate_reporting_token, ingest_sample

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.get("/allocation", response_model=AgentAllocation)
def get_allocation(
    response: Response,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AgentAllocation:
    """Read the approved allocation without starting or extending its lifetime."""
    resource, request = authenticate_reporting_token(db, parse_bearer(authorization))
    applicant = db.get(User, request.applicant_id)
    project = db.get(Project, request.project_id)
    if (
        resource.disabled_at is not None
        or applicant is None
        or applicant.status != "active"
        or project is None
        or project.status != "active"
    ):
        raise HTTPException(409, "申请关联的用户、Squad 或服务器已禁用")
    if request.expires_at is not None and as_utc(request.expires_at) <= utcnow():
        raise HTTPException(409, "申请已到期，不能创建或重建容器")
    container = db.scalar(
        select(ContainerInstance).where(
            ContainerInstance.compute_request_id == request.id,
            ContainerInstance.removed_at.is_(None),
        )
    )
    if container is not None:
        raise HTTPException(
            409,
            f"该申请已关联容器 {container.name}；请启动原容器，或删除旧容器并在监控页面移除记录后重建",
        )
    response.headers["Cache-Control"] = "no-store"
    return AgentAllocation(
        request_id=request.id,
        resource_name=resource.name,
        gpu_model=resource.gpu_model,
        gpu_count=request.gpu_count,
        cpu_cores=request.cpu_cores,
        memory_gib=request.memory_gib,
        expires_at=request.expires_at,
    )


@router.post("/samples", response_model=SampleAccepted)
def upload_samples(
    payload: SampleInput,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> SampleAccepted:
    token = parse_bearer(authorization)
    resource, request = authenticate_reporting_token(db, token)
    result, container = ingest_sample(db, resource, payload, request)
    return SampleAccepted(status=result, container_id=container.id)  # type: ignore[arg-type]

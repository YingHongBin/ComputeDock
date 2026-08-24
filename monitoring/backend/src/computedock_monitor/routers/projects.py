from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auditing import record_audit
from ..auth import AuthContext, require_admin_csrf, require_user
from ..database import get_db
from ..models import ComputeRequest, ComputeRequestChange, Project
from ..schemas import ProjectInput, ProjectView
from ..security import utcnow

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def project_view(project: Project) -> ProjectView:
    return ProjectView(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,  # type: ignore[arg-type]
        created_at=project.created_at,
    )


@router.get("", response_model=list[ProjectView])
def list_projects(
    include_disabled: bool = Query(default=False),
    auth: AuthContext = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[ProjectView]:
    query = select(Project)
    if auth.user.role != "admin" or not include_disabled:
        query = query.where(Project.status == "active")
    projects = list(db.scalars(query.order_by(Project.created_at.desc())))
    return [project_view(project) for project in projects]


@router.post("", response_model=ProjectView, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ProjectView:
    now = utcnow()
    project = Project(
        id=uuid.uuid4(),
        name=payload.name,
        description=payload.description,
        status="active",
        created_by_id=auth.user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    record_audit(
        db,
        auth.user,
        "project.create",
        "project",
        project.id,
        after={"name": project.name, "description": project.description},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Squad name already exists") from exc
    return project_view(project)


@router.put("/{project_id}", response_model=ProjectView)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ProjectView:
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Squad not found")
    before = {
        "name": project.name,
        "description": project.description,
    }
    project.name = payload.name
    project.description = payload.description
    project.updated_at = utcnow()
    record_audit(
        db,
        auth.user,
        "project.update",
        "project",
        project.id,
        before=before,
        after={
            "name": project.name,
            "description": project.description,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Squad name already exists") from exc
    return project_view(project)


def reject_pending_for_project(
    db: Session, project_id: uuid.UUID, reviewer_id: uuid.UUID
) -> None:
    now = utcnow()
    reason = "关联Squad已禁用"
    request_ids = select(ComputeRequest.id).where(ComputeRequest.project_id == project_id)
    db.execute(
        update(ComputeRequest)
        .where(ComputeRequest.project_id == project_id, ComputeRequest.approval_status == "pending")
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


def set_project_status(
    project_id: uuid.UUID,
    target_status: str,
    auth: AuthContext,
    db: Session,
) -> ProjectView:
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Squad not found")
    before = project.status
    project.status = target_status
    project.updated_at = utcnow()
    if before != "disabled" and target_status == "disabled":
        reject_pending_for_project(db, project.id, auth.user.id)
    record_audit(
        db,
        auth.user,
        f"project.{target_status}",
        "project",
        project.id,
        before={"status": before},
        after={"status": target_status},
    )
    db.commit()
    return project_view(project)


@router.post("/{project_id}/disable", response_model=ProjectView)
def disable_project(
    project_id: uuid.UUID,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ProjectView:
    return set_project_status(project_id, "disabled", auth, db)


@router.post("/{project_id}/enable", response_model=ProjectView)
def enable_project(
    project_id: uuid.UUID,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ProjectView:
    return set_project_status(project_id, "active", auth, db)

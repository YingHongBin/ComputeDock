from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auditing import record_audit
from ..auth import AuthContext, require_admin_csrf, require_user
from ..database import get_db
from ..models import (
    ComputeRequest,
    ComputeRequestChange,
    Project,
    ProjectMember,
    User,
)
from ..schemas import ProjectInput, ProjectMemberView, ProjectView
from ..security import utcnow

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def project_members(db: Session, project_id: uuid.UUID) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
            .order_by(User.full_name, User.username)
        )
    )


def project_view(db: Session, project: Project) -> ProjectView:
    return ProjectView(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,  # type: ignore[arg-type]
        members=[
            ProjectMemberView(id=user.id, username=user.username, full_name=user.full_name)
            for user in project_members(db, project.id)
        ],
        created_at=project.created_at,
    )


def validated_members(db: Session, member_ids: list[uuid.UUID]) -> list[User]:
    if not member_ids:
        return []
    users = list(
        db.scalars(select(User).where(User.id.in_(member_ids), User.status == "active"))
    )
    if len(users) != len(member_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "member not found or disabled")
    return users


def replace_members(
    db: Session,
    project: Project,
    users: list[User],
    actor: User,
) -> None:
    db.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id))
    now = utcnow()
    for user in users:
        db.add(
            ProjectMember(
                project_id=project.id,
                user_id=user.id,
                added_by_id=actor.id,
                created_at=now,
            )
        )


@router.get("", response_model=list[ProjectView])
def list_projects(
    include_disabled: bool = Query(default=False),
    auth: AuthContext = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[ProjectView]:
    query = select(Project)
    if auth.user.role == "admin":
        if not include_disabled:
            query = query.where(Project.status == "active")
    else:
        query = query.join(ProjectMember).where(
            ProjectMember.user_id == auth.user.id,
            Project.status == "active",
        )
    projects = list(db.scalars(query.order_by(Project.created_at.desc())))
    return [project_view(db, project) for project in projects]


@router.post("", response_model=ProjectView, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ProjectView:
    members = validated_members(db, payload.member_ids)
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
    db.flush()
    replace_members(db, project, members, auth.user)
    record_audit(
        db,
        auth.user,
        "project.create",
        "project",
        project.id,
        after={
            "name": project.name,
            "member_ids": [str(user.id) for user in members],
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "project name already exists") from exc
    return project_view(db, project)


@router.put("/{project_id}", response_model=ProjectView)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> ProjectView:
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    old_members = [str(user.id) for user in project_members(db, project.id)]
    members = validated_members(db, payload.member_ids)
    before = {
        "name": project.name,
        "description": project.description,
        "member_ids": old_members,
    }
    project.name = payload.name
    project.description = payload.description
    project.updated_at = utcnow()
    replace_members(db, project, members, auth.user)
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
            "member_ids": [str(user.id) for user in members],
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "project name already exists") from exc
    return project_view(db, project)


def reject_pending_for_project(
    db: Session, project_id: uuid.UUID, reviewer_id: uuid.UUID
) -> None:
    now = utcnow()
    reason = "关联项目已禁用"
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
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
    return project_view(db, project)


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

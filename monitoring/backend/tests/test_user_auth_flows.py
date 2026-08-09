from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from computedock_monitor.config import Settings, get_settings
from computedock_monitor.database import get_db
from computedock_monitor.models import (
    Admin,
    AdminSession,
    AuditEvent,
    Base,
    ComputeRequest,
    ComputeRequestChange,
    ComputeResource,
    ContainerInstance,
    EmailActionToken,
    HourlyGpuRollup,
    NotificationOutbox,
    Project,
    ProjectMember,
    RegistrationRequest,
    User,
    WorkerCheckpoint,
)
from computedock_monitor.routers import (
    auth,
    compute_requests,
    history,
    projects,
    resources,
    users,
)
from computedock_monitor.security import digest_secret, hash_password, utcnow
from computedock_monitor.services import authenticate_reporting_token


def make_test_app(monkeypatch) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Admin.__table__,
            User.__table__,
            AdminSession.__table__,
            RegistrationRequest.__table__,
            EmailActionToken.__table__,
            Project.__table__,
            ProjectMember.__table__,
            ComputeResource.__table__,
            ComputeRequest.__table__,
            ComputeRequestChange.__table__,
            ContainerInstance.__table__,
            HourlyGpuRollup.__table__,
            NotificationOutbox.__table__,
            AuditEvent.__table__,
            WorkerCheckpoint.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    settings = Settings(
        database_url="sqlite://",
        admin_username="admin",
        admin_password="long-enough-admin-password",
        cookie_secure=False,
        public_base_url="https://monitor.example.test",
    )
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(projects.router)
    app.include_router(compute_requests.router)
    app.include_router(history.router)
    app.include_router(resources.router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(
        "computedock_monitor.notifications.make_email_action_token",
        lambda: "known-email-action-token-with-enough-length",
    )
    return TestClient(app), sessions


def seed_admin(sessions: sessionmaker[Session]) -> User:
    now = utcnow()
    admin = User(
        id=uuid.uuid4(),
        username="admin",
        full_name="Administrator",
        email="admin@example.test",
        email_verified_at=now,
        password_hash=hash_password("long-enough-admin-password"),
        role="admin",
        status="active",
        must_bind_email=False,
        created_at=now,
        updated_at=now,
    )
    with sessions() as db:
        db.add(admin)
        db.commit()
    return admin


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def test_verified_registration_requires_admin_approval(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    seed_admin(sessions)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice",
            "full_name": "Alice Zhang",
            "email": "alice@example.test",
            "password": "long-enough-user-password",
        },
    )
    assert response.status_code == 202

    response = client.post(
        "/api/v1/auth/verify-email",
        json={"token": "known-email-action-token-with-enough-length"},
    )
    assert response.status_code == 204
    with sessions() as db:
        registration = db.scalar(select(RegistrationRequest))
        assert registration is not None
        assert registration.status == "pending"
        assert db.scalar(
            select(NotificationOutbox).where(
                NotificationOutbox.template == "registration_pending_admin"
            )
        )

    csrf = login(client, "admin", "long-enough-admin-password")
    response = client.post(
        f"/api/v1/users/registrations/{registration.id}/review",
        json={"decision": "approved"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    user_csrf = login(client, "alice", "long-enough-user-password")
    assert user_csrf
    assert client.get("/api/v1/users").status_code == 403


def test_registration_verification_can_be_resent_and_invalidates_old_link(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    tokens = iter(
        (
            "first-registration-token-with-enough-length",
            "second-registration-token-with-enough-length",
        )
    )
    monkeypatch.setattr(
        "computedock_monitor.notifications.make_email_action_token",
        lambda: next(tokens),
    )
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "resend-user",
            "full_name": "Resend User",
            "email": "resend@example.test",
            "password": "long-enough-user-password",
        },
    )
    assert response.status_code == 202

    response = client.post(
        "/api/v1/auth/registration/resend",
        json={"identity": "RESEND@EXAMPLE.TEST"},
    )
    assert response.status_code == 202
    assert client.post(
        "/api/v1/auth/verify-email",
        json={"token": "first-registration-token-with-enough-length"},
    ).status_code == 400
    assert client.post(
        "/api/v1/auth/verify-email",
        json={"token": "second-registration-token-with-enough-length"},
    ).status_code == 204
    with sessions() as db:
        notices = list(
            db.scalars(
                select(NotificationOutbox).where(
                    NotificationOutbox.template == "registration_verify"
                )
            )
        )
        assert len(notices) == 2


def test_registration_resend_does_not_reveal_unknown_identity(monkeypatch) -> None:
    client, _ = make_test_app(monkeypatch)
    response = client.post(
        "/api/v1/auth/registration/resend",
        json={"identity": "unknown@example.test"},
    )
    assert response.status_code == 202
    assert response.json() == {"status": "verification_sent"}


def test_rejection_requires_comment(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    seed_admin(sessions)
    csrf = login(client, "admin", "long-enough-admin-password")
    response = client.post(
        "/api/v1/users/registrations/00000000-0000-0000-0000-000000000001/review",
        json={"decision": "rejected"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 422


def test_disabling_user_revokes_web_session(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    admin = seed_admin(sessions)
    now = utcnow()
    user = User(
        id=uuid.uuid4(),
        username="bob",
        full_name="Bob Li",
        email="bob@example.test",
        email_verified_at=now,
        password_hash=hash_password("long-enough-user-password"),
        role="user",
        status="active",
        must_bind_email=False,
        created_at=now,
        updated_at=now,
    )
    with sessions() as db:
        db.add(user)
        db.commit()
    login(client, "bob", "long-enough-user-password")
    client.cookies.clear()
    csrf = login(client, admin.username, "long-enough-admin-password")
    response = client.patch(
        f"/api/v1/users/{user.id}",
        json={"status": "disabled"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    client.cookies.clear()
    assert client.post(
        "/api/v1/auth/login",
        json={"username": "bob", "password": "long-enough-user-password"},
    ).status_code == 403


def test_project_creator_is_not_implicitly_a_member(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    admin = seed_admin(sessions)
    now = utcnow()
    member = User(
        id=uuid.uuid4(),
        username="member",
        full_name="Project Member",
        email="member@example.test",
        email_verified_at=now,
        password_hash=hash_password("long-enough-user-password"),
        role="user",
        status="active",
        must_bind_email=False,
        created_at=now,
        updated_at=now,
    )
    with sessions() as db:
        db.add(member)
        db.commit()
    csrf = login(client, admin.username, "long-enough-admin-password")
    response = client.post(
        "/api/v1/projects",
        json={
            "code": "proj-1",
            "name": "Project One",
            "description": "",
            "member_ids": [str(member.id)],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text
    assert [item["id"] for item in response.json()["members"]] == [str(member.id)]


def test_resource_tokens_are_hidden_from_regular_users(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    admin = seed_admin(sessions)
    now = utcnow()
    user = User(
        id=uuid.uuid4(),
        username="viewer",
        full_name="Resource Viewer",
        email="viewer@example.test",
        email_verified_at=now,
        password_hash=hash_password("long-enough-user-password"),
        role="user",
        status="active",
        must_bind_email=False,
        created_at=now,
        updated_at=now,
    )
    legacy = ComputeResource(
        id=uuid.uuid4(),
        name="legacy",
        gpu_model="A100",
        gpu_count=8,
        token_hash=digest_secret("cdr_legacy"),
        token="cdr_legacy",
        created_at=now,
        updated_at=now,
    )
    with sessions() as db:
        db.add_all([user, legacy])
        db.commit()
    csrf = login(client, admin.username, "long-enough-admin-password")
    response = client.post(
        "/api/v1/resources",
        json={"name": "new", "gpu_model": "H100", "gpu_count": 4},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    assert response.json()["token"] is None
    client.cookies.clear()
    login(client, user.username, "long-enough-user-password")
    response = client.get("/api/v1/resources")
    assert response.status_code == 200
    assert all(item["token"] is None for item in response.json())
    with sessions() as db:
        token_resource, token_request = authenticate_reporting_token(db, "cdr_legacy")
        assert token_resource.id == legacy.id
        assert token_request is None


def test_compute_request_token_is_admin_only_and_changes_are_reviewed(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    admin = seed_admin(sessions)
    now = utcnow()
    applicant = User(
        id=uuid.uuid4(),
        username="applicant",
        full_name="GPU Applicant",
        email="applicant@example.test",
        email_verified_at=now,
        password_hash=hash_password("long-enough-user-password"),
        role="user",
        status="active",
        must_bind_email=False,
        created_at=now,
        updated_at=now,
    )
    resource = ComputeResource(
        id=uuid.uuid4(),
        name="gpu-cluster",
        gpu_model="H100",
        gpu_count=8,
        created_at=now,
        updated_at=now,
    )
    project = Project(
        id=uuid.uuid4(),
        code="gpu-project",
        name="GPU Project",
        description="",
        status="active",
        created_by_id=admin.id,
        created_at=now,
        updated_at=now,
    )
    membership = ProjectMember(
        project_id=project.id,
        user_id=applicant.id,
        added_by_id=admin.id,
        created_at=now,
    )
    with sessions() as db:
        db.add_all([applicant, resource, project, membership])
        db.commit()

    applicant_csrf = login(client, applicant.username, "long-enough-user-password")
    response = client.post(
        "/api/v1/compute-requests",
        json={
            "project_id": str(project.id),
            "resource_id": str(resource.id),
            "gpu_count": 2,
            "duration_days": 7,
        },
        headers={"X-CSRF-Token": applicant_csrf},
    )
    assert response.status_code == 201, response.text
    request_id = response.json()["id"]
    assert response.json()["token"] is None

    client.cookies.clear()
    admin_csrf = login(client, admin.username, "long-enough-admin-password")
    response = client.post(
        f"/api/v1/compute-requests/{request_id}/review",
        json={"decision": "approved"},
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert response.status_code == 200, response.text
    assert response.json()["token"].startswith("cda_")
    approved_token = response.json()["token"]
    with sessions() as db:
        token_resource, token_request = authenticate_reporting_token(
            db, response.json()["token"]
        )
        assert token_resource.id == resource.id
        assert token_request is not None
        assert str(token_request.id) == request_id

    client.cookies.clear()
    applicant_csrf = login(client, applicant.username, "long-enough-user-password")
    response = client.get(f"/api/v1/compute-requests/{request_id}")
    assert response.json()["token"] is None
    response = client.post(
        f"/api/v1/compute-requests/{request_id}/changes",
        json={"change_type": "extend", "amount": 14},
        headers={"X-CSRF-Token": applicant_csrf},
    )
    assert response.status_code == 409
    with sessions() as db:
        request = db.get(ComputeRequest, uuid.UUID(request_id))
        assert request is not None
        request.started_at = now
        request.expires_at = now + timedelta(days=request.duration_days)
        db.commit()
    response = client.post(
        f"/api/v1/compute-requests/{request_id}/changes",
        json={"change_type": "extend", "amount": 14},
        headers={"X-CSRF-Token": applicant_csrf},
    )
    assert response.status_code == 201, response.text
    change_id = response.json()["id"]
    pending_response = client.post(
        "/api/v1/compute-requests",
        json={
            "project_id": str(project.id),
            "resource_id": str(resource.id),
            "gpu_count": 1,
            "duration_days": 1,
        },
        headers={"X-CSRF-Token": applicant_csrf},
    )
    assert pending_response.status_code == 201, pending_response.text
    pending_request_id = pending_response.json()["id"]

    client.cookies.clear()
    admin_csrf = login(client, admin.username, "long-enough-admin-password")
    response = client.post(
        f"/api/v1/compute-requests/{request_id}/changes/{change_id}/review",
        json={"decision": "approved"},
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert response.status_code == 200, response.text
    with sessions() as db:
        request = db.get(ComputeRequest, uuid.UUID(request_id))
        assert request is not None
        assert request.duration_days == 21
        container = ContainerInstance(
            id=uuid.uuid4(),
            resource_id=resource.id,
            compute_request_id=request.id,
            name="worker-01",
            generation=1,
            first_reported_at=now,
            last_received_at=now,
            latest_collected_at=now,
            current_gpu_ids=["GPU-1"],
            removed_at=now,
        )
        db.add(container)
        db.flush()
        db.add(
            HourlyGpuRollup(
                id=1,
                bucket_start=now,
                resource_id=resource.id,
                compute_request_id=request.id,
                container_id=container.id,
                gpuid="GPU-1",
                utilization_avg=40.0,
                utilization_max=80,
                memory_used_avg=1024.0,
                memory_used_max=2048,
                memory_total=81920,
                online_seconds=3500,
                sample_count=240,
                first_collected_at=now,
                last_collected_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    response = client.get(f"/api/v1/history/containers?user_id={applicant.id}")
    assert response.status_code == 200, response.text
    assert response.json()[0]["name"] == "worker-01"
    response = client.get(f"/api/v1/history/containers/{container.id}/chart")
    assert response.status_code == 200, response.text
    assert response.json()["series"][0]["points"][0]["utilization_max"] == 80

    response = client.patch(
        f"/api/v1/users/{applicant.id}",
        json={"status": "disabled"},
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert response.status_code == 200, response.text
    response = client.get(f"/api/v1/compute-requests/{pending_request_id}")
    assert response.json()["approval_status"] == "rejected"
    assert response.json()["review_comment"] == "关联用户已禁用"
    assert client.post(
        f"/api/v1/projects/{project.id}/disable",
        headers={"X-CSRF-Token": admin_csrf},
    ).status_code == 200
    assert client.post(
        f"/api/v1/resources/{resource.id}/disable",
        headers={"X-CSRF-Token": admin_csrf},
    ).status_code == 200
    with sessions() as db:
        token_resource, token_request = authenticate_reporting_token(db, approved_token)
        assert token_resource.id == resource.id
        assert token_request is not None
        assert str(token_request.id) == request_id


def test_admin_can_approve_own_compute_request(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    admin = seed_admin(sessions)
    now = utcnow()
    resource = ComputeResource(
        id=uuid.uuid4(),
        name="self-review-cluster",
        gpu_model="H100",
        gpu_count=2,
        created_at=now,
        updated_at=now,
    )
    project = Project(
        id=uuid.uuid4(),
        code="self-review-project",
        name="Self Review Project",
        description="",
        status="active",
        created_by_id=admin.id,
        created_at=now,
        updated_at=now,
    )
    membership = ProjectMember(
        project_id=project.id,
        user_id=admin.id,
        added_by_id=admin.id,
        created_at=now,
    )
    with sessions() as db:
        db.add_all([resource, project, membership])
        db.commit()

    csrf = login(client, admin.username, "long-enough-admin-password")
    response = client.post(
        "/api/v1/compute-requests",
        json={
            "project_id": str(project.id),
            "resource_id": str(resource.id),
            "gpu_count": 1,
            "duration_days": 1,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text
    response = client.post(
        f"/api/v1/compute-requests/{response.json()['id']}/review",
        json={"decision": "approved"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    assert response.json()["token"].startswith("cda_")

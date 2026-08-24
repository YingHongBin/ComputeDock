from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from computedock_monitor.config import Settings, get_settings
from computedock_monitor.database import get_db
from computedock_monitor.models import (
    AdminSession,
    AuditEvent,
    Base,
    ComputeRequest,
    ComputeRequestChange,
    ComputeResource,
    ContainerInstance,
    EmailActionToken,
    GpuSample,
    HourlyGpuRollup,
    NotificationOutbox,
    Project,
    ProjectMember,
    RegistrationRequest,
    SmtpSetting,
    SystemSetting,
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
from computedock_monitor.routers import settings as settings_router
from computedock_monitor.security import hash_password, utcnow, verify_password
from computedock_monitor.services import authenticate_reporting_token
from computedock_monitor.worker import (
    enqueue_low_utilization_warnings,
    summarize_pending_containers,
)


def make_test_app(monkeypatch) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
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
            SmtpSetting.__table__,
            SystemSetting.__table__,
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
        admin_full_name="Administrator",
        admin_email="admin@example.test",
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
    app.include_router(settings_router.router)
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


def test_initial_admin_is_a_verified_user(monkeypatch) -> None:
    from computedock_monitor import main as main_module

    _client, sessions = make_test_app(monkeypatch)
    settings = Settings(
        database_url="sqlite://",
        admin_username="InitialAdmin",
        admin_password="long-enough-initial-password",
        admin_full_name="Initial Administrator",
        admin_email="Initial.Admin@Example.Test",
    )
    monkeypatch.setattr(main_module, "SessionLocal", sessions)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    main_module.ensure_initial_admin()

    with sessions() as db:
        users_in_database = list(db.scalars(select(User)))
        assert len(users_in_database) == 1
        admin = users_in_database[0]
        assert admin.username == "InitialAdmin"
        assert admin.full_name == "Initial Administrator"
        assert admin.email == "initial.admin@example.test"
        assert admin.email_verified_at is not None
        assert admin.role == "admin"
        assert admin.status == "active"
        assert verify_password(admin.password_hash, "long-enough-initial-password")


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
    assert (
        client.post(
            "/api/v1/auth/verify-email",
            json={"token": "first-registration-token-with-enough-length"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/verify-email",
            json={"token": "second-registration-token-with-enough-length"},
        ).status_code
        == 204
    )
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
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "bob", "password": "long-enough-user-password"},
        ).status_code
        == 403
    )


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
            "name": "Project One",
            "description": "",
            "member_ids": [str(member.id)],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text
    assert "code" not in response.json()
    assert [item["id"] for item in response.json()["members"]] == [str(member.id)]
    second = client.post(
        "/api/v1/projects",
        json={"name": "Project Two", "description": "", "member_ids": []},
        headers={"X-CSRF-Token": csrf},
    )
    assert second.status_code == 201, second.text
    assert "code" not in second.json()
    with sessions() as db:
        internal_codes = list(db.scalars(select(Project.code)))
    assert len(internal_codes) == len(set(internal_codes)) == 2


def test_admin_can_save_and_test_smtp_without_password_disclosure(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    admin = seed_admin(sessions)
    csrf = login(client, admin.username, "long-enough-admin-password")

    response = client.get("/api/v1/settings/smtp")
    assert response.status_code == 200
    assert response.json()["source"] == "environment"
    assert response.json()["password_set"] is False
    assert "password" not in response.json()

    payload = {
        "host": "smtp.example.test",
        "port": 587,
        "username": "smtp-user",
        "password": "smtp-secret",
        "from_email": "monitor@example.test",
        "from_name": "ComputeDock Monitor",
        "use_tls": True,
    }
    response = client.put(
        "/api/v1/settings/smtp",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "database"
    assert response.json()["password_set"] is True
    assert "password" not in response.json()

    response = client.put(
        "/api/v1/settings/smtp",
        json={**payload, "host": "smtp2.example.test", "password": None},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    with sessions() as db:
        saved = db.get(SmtpSetting, 1)
        assert saved is not None
        assert saved.host == "smtp2.example.test"
        assert saved.password == "smtp-secret"

    sent: dict[str, object] = {}

    def fake_send_email(connection, **kwargs) -> None:
        sent["connection"] = connection
        sent.update(kwargs)

    monkeypatch.setattr(settings_router, "send_email", fake_send_email)
    response = client.post(
        "/api/v1/settings/smtp/test",
        json={**payload, "host": "smtp2.example.test", "password": None},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "sent", "recipient": admin.email}
    assert sent["to_address"] == admin.email
    assert sent["connection"].password == "smtp-secret"  # type: ignore[union-attr]


def test_admin_can_set_api_base_url_for_email_links(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    admin = seed_admin(sessions)
    csrf = login(client, admin.username, "long-enough-admin-password")

    response = client.get("/api/v1/settings/general")
    assert response.status_code == 200
    assert response.json() == {
        "api_base_url": "https://monitor.example.test",
        "low_utilization_warning_enabled": True,
        "low_utilization_threshold": 10,
        "source": "environment",
    }

    response = client.put(
        "/api/v1/settings/general",
        json={
            "api_base_url": "https://public.example.test/monitor/",
            "low_utilization_warning_enabled": True,
            "low_utilization_threshold": 15,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "api_base_url": "https://public.example.test/monitor",
        "low_utilization_warning_enabled": True,
        "low_utilization_threshold": 15,
        "source": "database",
    }

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "base-url-user",
            "full_name": "Base URL User",
            "email": "base-url@example.test",
            "password": "long-enough-user-password",
        },
    )
    assert response.status_code == 202, response.text
    with sessions() as db:
        notice = db.scalar(
            select(NotificationOutbox).where(NotificationOutbox.template == "registration_verify")
        )
        assert notice is not None
        assert notice.payload["action_url"].startswith(
            "https://public.example.test/monitor/verify-email?token="
        )


def test_low_utilization_warnings_group_containers_by_request(monkeypatch) -> None:
    _client, sessions = make_test_app(monkeypatch)
    admin = seed_admin(sessions)
    target_day = date(2026, 8, 10)
    window_start = datetime(2026, 8, 9, 16, tzinfo=UTC)
    first_reported = window_start + timedelta(minutes=10)
    container_specs = (
        ("training-a", 5.0, window_start + timedelta(hours=14)),
        ("training-b", 8.0, window_start + timedelta(hours=14)),
        ("too-short", 2.0, window_start + timedelta(hours=11)),
        ("at-threshold", 10.0, window_start + timedelta(hours=14)),
    )
    applicant = User(
        id=uuid.uuid4(),
        username="low-usage-user",
        full_name="Low Usage User",
        email="low-usage@example.test",
        email_verified_at=window_start,
        password_hash=hash_password("long-enough-user-password"),
        role="user",
        status="active",
        created_at=window_start,
        updated_at=window_start,
    )
    resource = ComputeResource(
        id=uuid.uuid4(),
        name="Low Usage Cluster",
        gpu_model="H100",
        gpu_count=8,
        created_at=window_start,
        updated_at=window_start,
    )
    project = Project(
        id=uuid.uuid4(),
        name="Low Usage Project",
        description="",
        status="active",
        created_by_id=admin.id,
        created_at=window_start,
        updated_at=window_start,
    )
    request = ComputeRequest(
        id=uuid.uuid4(),
        applicant_id=applicant.id,
        project_id=project.id,
        resource_id=resource.id,
        gpu_count=4,
        duration_days=7,
        approval_status="approved",
        created_at=window_start,
        updated_at=window_start,
    )
    containers = [
        ContainerInstance(
            id=uuid.uuid4(),
            resource_id=resource.id,
            compute_request_id=request.id,
            name=name,
            generation=1,
            first_reported_at=first_reported,
            last_received_at=last_reported,
            latest_collected_at=last_reported,
            current_gpu_ids=["GPU-1", "GPU-2"],
        )
        for name, _utilization, last_reported in container_specs
    ]
    with sessions() as db:
        db.add_all([applicant, resource, project, request, *containers])
        db.flush()
        rollup_id = 1
        for container, (_name, utilization, last_reported) in zip(
            containers, container_specs, strict=True
        ):
            for gpuid in ("GPU-1", "GPU-2"):
                db.add(
                    HourlyGpuRollup(
                        id=rollup_id,
                        bucket_start=window_start,
                        resource_id=resource.id,
                        compute_request_id=request.id,
                        container_id=container.id,
                        gpuid=gpuid,
                        utilization_avg=utilization,
                        utilization_max=int(utilization),
                        memory_used_avg=1024,
                        memory_used_max=1024,
                        memory_total=81920,
                        online_seconds=3600,
                        sample_count=2,
                        first_collected_at=first_reported,
                        last_collected_at=last_reported,
                        created_at=window_start,
                        updated_at=window_start,
                    )
                )
                rollup_id += 1
        db.commit()
    engine = sessions.kw["bind"]
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE gpu_samples (
                id bigint,
                collected_at datetime NOT NULL,
                received_at datetime NOT NULL,
                batch_id char(32) NOT NULL,
                resource_id char(32) NOT NULL,
                container_id char(32) NOT NULL,
                gpuid varchar(160) NOT NULL,
                memory_used bigint NOT NULL,
                memory_total bigint NOT NULL,
                utilization integer NOT NULL
            )
            """
        )
    with sessions() as db:
        sample_id = 1
        for container, (_name, _utilization, last_reported) in zip(
            containers, container_specs, strict=True
        ):
            for gpuid in ("GPU-1", "GPU-2"):
                for collected_at in (first_reported, last_reported):
                    db.execute(
                        GpuSample.__table__.insert().values(
                            id=sample_id,
                            collected_at=collected_at,
                            received_at=collected_at,
                            batch_id=uuid.uuid4(),
                            resource_id=resource.id,
                            container_id=container.id,
                            gpuid=gpuid,
                            memory_used=1024,
                            memory_total=81920,
                            utilization=5,
                        )
                    )
                    sample_id += 1
        db.commit()
        assert (
            enqueue_low_utilization_warnings(
                db,
                target_day,
                Settings(
                    database_url="sqlite://",
                    admin_username="admin",
                    admin_password="long-enough-admin-password",
                    admin_full_name="Administrator",
                    admin_email="admin@example.test",
                ),
                threshold=10,
            )
            == 1
        )
        notices = list(
            db.scalars(
                select(NotificationOutbox).where(
                    NotificationOutbox.template == "low_utilization_warning"
                )
            )
        )
        assert len(notices) == 1
        assert notices[0].to_address == applicant.email
        assert notices[0].cc_addresses == [admin.email]
        assert [item["name"] for item in notices[0].payload["containers"]] == [
            "training-a",
            "training-b",
        ]
        assert all(item["gpu_count"] == 2 for item in notices[0].payload["containers"])


def test_api_base_url_rejects_unsafe_values(monkeypatch) -> None:
    client, sessions = make_test_app(monkeypatch)
    admin = seed_admin(sessions)
    csrf = login(client, admin.username, "long-enough-admin-password")

    for value in (
        "smtp://public.example.test",
        "https://user:secret@public.example.test",
        "https://public.example.test?redirect=other",
        "https://public.example.test#fragment",
    ):
        response = client.put(
            "/api/v1/settings/general",
            json={"api_base_url": value},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 422, response.text

    response = client.put(
        "/api/v1/settings/general",
        json={
            "api_base_url": "https://public.example.test",
            "low_utilization_warning_enabled": True,
            "low_utilization_threshold": 101,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 422, response.text


def test_resources_do_not_have_reporting_tokens(monkeypatch) -> None:
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
        created_at=now,
        updated_at=now,
    )
    resource = ComputeResource(
        id=uuid.uuid4(),
        name="existing",
        gpu_model="A100",
        gpu_count=8,
        created_at=now,
        updated_at=now,
    )
    with sessions() as db:
        db.add_all([user, resource])
        db.commit()
    csrf = login(client, admin.username, "long-enough-admin-password")
    response = client.post(
        "/api/v1/resources",
        json={"name": "new", "gpu_model": "H100", "gpu_count": 4},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    assert "token" not in response.json()
    client.cookies.clear()
    login(client, user.username, "long-enough-user-password")
    response = client.get("/api/v1/resources")
    assert response.status_code == 200
    assert all("token" not in item for item in response.json())


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
        token_resource, token_request = authenticate_reporting_token(db, response.json()["token"])
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
            usage_summary_status="pending",
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
        db.add(
            WorkerCheckpoint(
                name="hourly_rollups",
                completed_through=now.date() + timedelta(days=1),
                updated_at=now,
            )
        )
        db.commit()
        assert (
            summarize_pending_containers(
                db,
                Settings(
                    database_url="sqlite://",
                    admin_username="admin",
                    admin_password="long-enough-admin-password",
                    admin_full_name="Administrator",
                    admin_email="admin@example.test",
                ),
            )
            == 1
        )
        db.refresh(container)
        assert container.usage_summary_status == "completed"
        assert container.usage_duration_seconds == 0
        assert container.usage_gpu_count == 1
        assert container.usage_gpu_utilization_avg == 40.0
        assert container.usage_gpu_utilization_max == 80
        assert container.usage_memory_utilization_avg == 1.25
        assert container.usage_memory_utilization_max == 2.5
    response = client.get(f"/api/v1/history/containers?user_id={applicant.id}")
    assert response.status_code == 200, response.text
    assert response.json()[0]["name"] == "worker-01"
    assert response.json()[0]["usage_summary_status"] == "completed"
    assert response.json()[0]["usage_gpu_utilization_avg"] == 40.0
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
    assert (
        client.post(
            f"/api/v1/projects/{project.id}/disable",
            headers={"X-CSRF-Token": admin_csrf},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/resources/{resource.id}/disable",
            headers={"X-CSRF-Token": admin_csrf},
        ).status_code
        == 200
    )
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

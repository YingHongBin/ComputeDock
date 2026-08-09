from __future__ import annotations

import uuid
from collections.abc import Generator

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
    EmailActionToken,
    NotificationOutbox,
    Project,
    RegistrationRequest,
    User,
)
from computedock_monitor.routers import auth, users
from computedock_monitor.security import hash_password, utcnow


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
            ComputeResource.__table__,
            ComputeRequest.__table__,
            ComputeRequestChange.__table__,
            NotificationOutbox.__table__,
            AuditEvent.__table__,
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

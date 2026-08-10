from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


JsonType = JSON().with_variant(JSONB(), "postgresql")


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    must_bind_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admins.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True, nullable=False)
    csrf_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    admin: Mapped[Admin | None] = relationship()
    user: Mapped[User | None] = relationship()


class RegistrationRequest(Base):
    __tablename__ = "registration_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="email_pending")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_registration_requests_status_created", "status", "created_at"),)


class EmailActionToken(Base):
    __tablename__ = "email_action_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    registration_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("registration_requests.id", ondelete="CASCADE")
    )
    pending_email: Mapped[str | None] = mapped_column(String(320))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_email_action_tokens_expiry", "expires_at"),)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    added_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ComputeResource(Base):
    __tablename__ = "compute_resources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    gpu_model: Mapped[str] = mapped_column(String(200), nullable=False)
    gpu_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), unique=True)
    token: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )

    containers: Mapped[list[ContainerInstance]] = relationship(back_populates="resource")

    __table_args__ = (
        Index(
            "uq_compute_resources_active_name",
            "name",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )


class ComputeRequest(Base):
    __tablename__ = "compute_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("compute_resources.id", ondelete="RESTRICT"), nullable=False
    )
    gpu_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), unique=True)
    token: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_compute_requests_applicant_created", "applicant_id", "created_at"),
        Index("ix_compute_requests_project_created", "project_id", "created_at"),
        Index("ix_compute_requests_resource_status", "resource_id", "approval_status"),
    )


class ComputeRequestChange(Base):
    __tablename__ = "compute_request_changes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("compute_requests.id", ondelete="RESTRICT"), nullable=False
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    before_value: Mapped[int] = mapped_column(Integer, nullable=False)
    after_value: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_compute_request_changes_request_created", "request_id", "created_at"),
    )


class ContainerInstance(Base):
    __tablename__ = "container_instances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("compute_resources.id", ondelete="RESTRICT"), nullable=False
    )
    compute_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("compute_requests.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_gpu_ids: Mapped[list[str]] = mapped_column(JsonType, nullable=False, default=list)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    resource: Mapped[ComputeResource] = relationship(back_populates="containers")
    batches: Mapped[list[SampleBatch]] = relationship(back_populates="container")

    __table_args__ = (
        Index(
            "uq_container_legacy_generation",
            "resource_id",
            "name",
            "generation",
            unique=True,
            postgresql_where=text("compute_request_id IS NULL"),
            sqlite_where=text("compute_request_id IS NULL"),
        ),
        Index(
            "uq_container_request_generation",
            "compute_request_id",
            "name",
            "generation",
            unique=True,
            postgresql_where=text("compute_request_id IS NOT NULL"),
            sqlite_where=text("compute_request_id IS NOT NULL"),
        ),
        Index(
            "uq_container_legacy_active_name",
            "resource_id",
            "name",
            unique=True,
            postgresql_where=text("removed_at IS NULL AND compute_request_id IS NULL"),
            sqlite_where=text("removed_at IS NULL AND compute_request_id IS NULL"),
        ),
        Index(
            "uq_container_request_active_name",
            "compute_request_id",
            "name",
            unique=True,
            postgresql_where=text("removed_at IS NULL AND compute_request_id IS NOT NULL"),
            sqlite_where=text("removed_at IS NULL AND compute_request_id IS NOT NULL"),
        ),
        Index("ix_container_resource_active", "resource_id", "removed_at"),
        Index("ix_container_request_active", "compute_request_id", "removed_at"),
    )


class SampleBatch(Base):
    __tablename__ = "sample_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    container_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("container_instances.id", ondelete="RESTRICT"), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)

    container: Mapped[ContainerInstance] = relationship(back_populates="batches")

    __table_args__ = (
        UniqueConstraint("container_id", "collected_at", name="uq_batch_container_collected"),
        {"postgresql_partition_by": "RANGE (collected_at)"},
    )


class GpuSample(Base):
    __tablename__ = "gpu_samples"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    container_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    gpuid: Mapped[str] = mapped_column(String(160), nullable=False)
    memory_used: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memory_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    utilization: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("container_id", "gpuid", "collected_at", name="uq_gpu_sample_identity"),
        Index("ix_gpu_samples_container_time", "container_id", "collected_at"),
        Index("ix_gpu_samples_resource_time", "resource_id", "collected_at"),
        {"postgresql_partition_by": "RANGE (collected_at)"},
    )


class HourlyGpuRollup(Base):
    __tablename__ = "hourly_gpu_rollups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("compute_resources.id", ondelete="RESTRICT"), nullable=False
    )
    compute_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("compute_requests.id", ondelete="RESTRICT")
    )
    container_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("container_instances.id", ondelete="RESTRICT"), nullable=False
    )
    gpuid: Mapped[str] = mapped_column(String(160), nullable=False)
    utilization_avg: Mapped[float] = mapped_column(Float, nullable=False)
    utilization_max: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_used_avg: Mapped[float] = mapped_column(Float, nullable=False)
    memory_used_max: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memory_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    online_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "container_id", "gpuid", "bucket_start", name="uq_hourly_gpu_rollup_identity"
        ),
        Index("ix_hourly_rollups_resource_time", "resource_id", "bucket_start"),
        Index("ix_hourly_rollups_request_time", "compute_request_id", "bucket_start"),
        Index("ix_hourly_rollups_container_time", "container_id", "bucket_start"),
    )


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(240), unique=True, nullable=False)
    template: Mapped[str] = mapped_column(String(80), nullable=False)
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    cc_addresses: Mapped[list[str]] = mapped_column(JsonType, nullable=False, default=list)
    payload: Mapped[dict[str, object]] = mapped_column(JsonType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_notification_outbox_delivery", "status", "available_at"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    object_id: Mapped[str] = mapped_column(String(100), nullable=False)
    before: Mapped[dict[str, object] | None] = mapped_column(JsonType)
    after: Mapped[dict[str, object] | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_events_object", "object_type", "object_id", "created_at"),
        Index("ix_audit_events_actor_created", "actor_id", "created_at"),
    )


class WorkerCheckpoint(Base):
    __tablename__ = "worker_checkpoints"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    completed_through: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

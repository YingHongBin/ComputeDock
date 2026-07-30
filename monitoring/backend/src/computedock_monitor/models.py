from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
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


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("admins.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True, nullable=False)
    csrf_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    admin: Mapped[Admin] = relationship()


class ComputeResource(Base):
    __tablename__ = "compute_resources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    gpu_model: Mapped[str] = mapped_column(String(200), nullable=False)
    gpu_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True, nullable=False)
    token: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    containers: Mapped[list[ContainerInstance]] = relationship(back_populates="resource")

    __table_args__ = (
        CheckConstraint("gpu_count > 0", name="ck_compute_resources_gpu_count_positive"),
        Index(
            "uq_compute_resources_active_name",
            "name",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )


class ContainerInstance(Base):
    __tablename__ = "container_instances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("compute_resources.id", ondelete="RESTRICT"), nullable=False
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
        UniqueConstraint("resource_id", "name", "generation", name="uq_container_generation"),
        Index(
            "uq_container_active_name",
            "resource_id",
            "name",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index("ix_container_resource_active", "resource_id", "removed_at"),
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
        CheckConstraint("memory_total > 0", name="ck_gpu_samples_memory_total"),
        CheckConstraint(
            "memory_used >= 0 AND memory_used <= memory_total",
            name="ck_gpu_samples_memory_used",
        ),
        CheckConstraint(
            "utilization >= 0 AND utilization <= 100", name="ck_gpu_samples_utilization"
        ),
        Index("ix_gpu_samples_container_time", "container_id", "collected_at"),
        Index("ix_gpu_samples_resource_time", "resource_id", "collected_at"),
        {"postgresql_partition_by": "RANGE (collected_at)"},
    )

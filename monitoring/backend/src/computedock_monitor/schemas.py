from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        return value.strip()


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class AdminView(BaseModel):
    username: str
    full_name: str
    email: str | None
    email_verified: bool
    must_bind_email: bool
    role: Literal["admin", "user"]
    csrf_token: str


class RegistrationInput(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)

    @field_validator("username", "full_name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        local, separator, domain = value.partition("@")
        if separator != "@" or not local or "." not in domain or domain.startswith("."):
            raise ValueError("invalid email address")
        return value


class EmailTokenInput(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class PasswordResetRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=320)


class PasswordResetConfirm(EmailTokenInput):
    new_password: str = Field(min_length=12, max_length=256)


class EmailChangeRequest(BaseModel):
    current_password: str
    new_email: str = Field(min_length=3, max_length=320)

    @field_validator("new_email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return RegistrationInput.normalize_email(value)


class RegistrationRequestView(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str
    email: str
    status: Literal["email_pending", "pending", "approved", "rejected"]
    email_verified_at: datetime | None
    review_comment: str | None
    reviewed_at: datetime | None
    created_at: datetime


class ReviewInput(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str | None = Field(default=None, max_length=4000)

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_rejection_comment(self):
        if self.decision == "rejected" and self.comment is None:
            raise ValueError("rejection comment is required")
        return self


class UserView(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str
    email: str | None
    email_verified_at: datetime | None
    role: Literal["admin", "user"]
    status: Literal["active", "disabled"]
    must_bind_email: bool
    created_at: datetime


class UserAdminUpdate(BaseModel):
    role: Literal["admin", "user"] | None = None
    status: Literal["active", "disabled"] | None = None


class SmtpSettingsInput(BaseModel):
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(default="", max_length=320)
    password: str | None = Field(default=None, max_length=1024)
    from_email: str = Field(default="", max_length=320)
    from_name: str = Field(default="ComputeDock", max_length=200)
    use_tls: bool = True

    @field_validator("host", "username", "from_name")
    @classmethod
    def strip_smtp_text(cls, value: str) -> str:
        value = value.strip()
        if "\r" in value or "\n" in value:
            raise ValueError("must not contain newlines")
        return value

    @field_validator("from_email")
    @classmethod
    def normalize_from_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            return value
        return RegistrationInput.normalize_email(value)


class SmtpSettingsView(BaseModel):
    host: str
    port: int
    username: str
    from_email: str
    from_name: str
    use_tls: bool
    password_set: bool
    source: Literal["database", "environment"]


class GeneralSettingsInput(BaseModel):
    api_base_url: str = Field(min_length=1, max_length=2048)

    @field_validator("api_base_url")
    @classmethod
    def validate_api_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("must be an HTTP(S) base URL without query or fragment")
        return value


class GeneralSettingsView(BaseModel):
    api_base_url: str
    source: Literal["database", "environment"]


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    member_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def strip_project_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("member_ids")
    @classmethod
    def unique_members(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("member_ids must be unique")
        return value


class ProjectMemberView(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str


class ProjectView(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    status: Literal["active", "disabled"]
    members: list[ProjectMemberView]
    created_at: datetime


class ComputeRequestInput(BaseModel):
    project_id: uuid.UUID
    resource_id: uuid.UUID
    gpu_count: int = Field(gt=0)
    duration_days: int = Field(ge=1, le=14)


class ComputeRequestChangeInput(BaseModel):
    change_type: Literal["extend", "expand", "release"]
    amount: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_extension_days(self):
        if self.change_type == "extend" and self.amount > 14:
            raise ValueError("extension days must be between 1 and 14")
        return self


class ComputeRequestChangeView(BaseModel):
    id: uuid.UUID
    change_type: Literal["extend", "expand", "release"]
    amount: int
    approval_status: Literal["pending", "approved", "rejected"]
    before_value: int
    after_value: int
    reviewer_name: str | None
    review_comment: str | None
    reviewed_at: datetime | None
    created_at: datetime


class ComputeRequestView(BaseModel):
    id: uuid.UUID
    applicant_id: uuid.UUID
    applicant_username: str
    applicant_name: str
    project_id: uuid.UUID
    project_name: str
    resource_id: uuid.UUID
    resource_name: str
    gpu_count: int
    duration_days: int
    approval_status: Literal["pending", "approved", "rejected"]
    runtime_status: Literal["not_started", "running", "expiring", "expired"] | None
    actual_gpu_count: int
    over_quota: bool
    reviewer_name: str | None
    review_comment: str | None
    reviewed_at: datetime | None
    token: str | None
    started_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    changes: list[ComputeRequestChangeView]


class HistoryContainerView(BaseModel):
    id: uuid.UUID
    name: str
    generation: int
    status: Literal["online", "offline", "removed"]
    applicant_id: uuid.UUID
    applicant_name: str
    project_id: uuid.UUID
    project_name: str
    resource_id: uuid.UUID
    resource_name: str
    compute_request_id: uuid.UUID
    first_reported_at: datetime
    last_received_at: datetime
    removed_at: datetime | None
    expires_at: datetime | None


class HourlyHistoryPoint(BaseModel):
    time: datetime
    utilization_avg: float
    utilization_max: int
    memory_used_avg: float
    memory_used_max: int
    memory_total: int
    online_seconds: int
    sample_count: int


class HourlyHistorySeries(BaseModel):
    gpuid: str
    points: list[HourlyHistoryPoint]


class HistoryContainerChart(BaseModel):
    container_id: uuid.UUID
    container_name: str
    first_reported_at: datetime
    removed_at: datetime
    series: list[HourlyHistorySeries]


class ResourceInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    gpu_model: str = Field(min_length=1, max_length=200)
    gpu_count: int = Field(gt=0, le=10000)

    @field_validator("name", "gpu_model")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ResourceCard(BaseModel):
    id: uuid.UUID
    name: str
    gpu_model: str
    gpu_count: int
    allocated_gpu_count: int
    available_gpu_count: int
    overallocated: bool
    status: Literal["active", "disabled"] = "active"
    token: str | None = None


class ResourceDetail(ResourceCard):
    created_at: datetime


class GpuMetricInput(BaseModel):
    gpuid: str = Field(min_length=1, max_length=160)
    memory_used: int = Field(ge=0)
    memory_total: int = Field(gt=0)
    utilization: int = Field(ge=0, le=100)

    @field_validator("gpuid")
    @classmethod
    def strip_gpuid(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("gpuid must not be blank")
        return value


class SampleInput(BaseModel):
    container_name: str = Field(min_length=1, max_length=255)
    collected_at: datetime
    gpus: list[GpuMetricInput] = Field(min_length=1, max_length=64)

    @field_validator("container_name")
    @classmethod
    def strip_container_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("container_name must not be blank")
        return value

    @field_validator("gpus")
    @classmethod
    def validate_gpu_batch(cls, gpus: list[GpuMetricInput]) -> list[GpuMetricInput]:
        ids = [gpu.gpuid for gpu in gpus]
        if len(ids) != len(set(ids)):
            raise ValueError("gpuid must be unique within a batch")
        for gpu in gpus:
            if gpu.memory_used > gpu.memory_total:
                raise ValueError("memory_used must not exceed memory_total")
        return gpus


class SampleAccepted(BaseModel):
    status: Literal["accepted", "duplicate"]
    container_id: uuid.UUID


class ContainerSummary(BaseModel):
    id: uuid.UUID
    name: str
    generation: int
    status: Literal["online", "offline"]
    last_received_at: datetime
    allocated_gpu_count: int
    utilization_1h: float | None
    utilization_6h: float | None
    utilization_1d: float | None
    utilization_7d: float | None


class ChartPoint(BaseModel):
    time: datetime
    memory_used: float | None
    memory_total: float | None
    utilization: float | None


class GpuChartSeries(BaseModel):
    gpuid: str
    shared: bool
    first_reported_at: datetime
    last_reported_at: datetime
    points: list[ChartPoint]


class ChartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    container_id: uuid.UUID
    container_name: str
    range: Literal["1h", "6h", "1d", "7d"]
    bucket_seconds: int
    window_start: datetime
    window_end: datetime
    instance_first_reported_at: datetime
    instance_removed_at: datetime | None
    series: list[GpuChartSeries]

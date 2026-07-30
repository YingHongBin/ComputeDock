from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class AdminView(BaseModel):
    username: str
    csrf_token: str


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
    token: str


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

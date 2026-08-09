import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from computedock_monitor.models import ComputeRequest, ComputeResource, ContainerInstance
from computedock_monitor.schemas import SampleInput
from computedock_monitor.services import (
    RANGES,
    aligned_chart_window,
    canonical_payload_hash,
    resource_card,
    start_compute_request,
    validate_collection_time,
)


def test_resource_allocation_deduplicates_shared_gpu() -> None:
    resource = ComputeResource(
        id=uuid.uuid4(), name="r", gpu_model="A100", gpu_count=2, token="cdr_token"
    )
    containers = [
        ContainerInstance(current_gpu_ids=["GPU-1", "GPU-2"], removed_at=None),
        ContainerInstance(current_gpu_ids=["GPU-1"], removed_at=None),
    ]
    card = resource_card(resource, containers)
    assert card.token == "cdr_token"
    assert card.allocated_gpu_count == 2
    assert card.available_gpu_count == 0


def test_resource_allocation_marks_overallocation() -> None:
    resource = ComputeResource(
        id=uuid.uuid4(), name="r", gpu_model="A100", gpu_count=1, token="cdr_token"
    )
    card = resource_card(
        resource,
        [ContainerInstance(current_gpu_ids=["GPU-1", "GPU-2"], removed_at=None)],
    )
    assert card.overallocated
    assert card.available_gpu_count == 0


def test_payload_hash_is_gpu_order_independent() -> None:
    now = datetime.now(UTC)
    first = SampleInput.model_validate(
        {
            "container_name": "worker",
            "collected_at": now,
            "gpus": [
                {"gpuid": "GPU-2", "memory_used": 2, "memory_total": 10, "utilization": 20},
                {"gpuid": "GPU-1", "memory_used": 1, "memory_total": 10, "utilization": 10},
            ],
        }
    )
    second = first.model_copy(update={"gpus": list(reversed(first.gpus))})
    assert canonical_payload_hash(first) == canonical_payload_hash(second)


def test_collection_time_limits() -> None:
    now = datetime.now(UTC)
    assert validate_collection_time(now, now) == now
    for invalid in (now + timedelta(minutes=6), now - timedelta(hours=25)):
        with pytest.raises(HTTPException) as error:
            validate_collection_time(invalid, now)
        assert error.value.status_code == 422


def test_chart_ranges_match_contract() -> None:
    assert {name: seconds for name, (_, seconds) in RANGES.items()} == {
        "1h": 60,
        "6h": 300,
        "1d": 900,
        "7d": 3600,
    }


def test_chart_window_aligns_to_bucket_boundaries() -> None:
    now = datetime(2026, 7, 30, 8, 18, 42, 123456, tzinfo=UTC)
    start, end = aligned_chart_window(now, timedelta(hours=1), 60)
    assert end == datetime(2026, 7, 30, 8, 19, tzinfo=UTC)
    assert start == datetime(2026, 7, 30, 7, 19, tzinfo=UTC)


def test_compute_request_starts_once_from_first_received_report() -> None:
    request = ComputeRequest(duration_days=7)
    first = datetime(2026, 8, 10, 1, 2, 3, tzinfo=UTC)
    second = first + timedelta(hours=1)
    assert start_compute_request(request, first)
    assert request.started_at == first
    assert request.expires_at == first + timedelta(days=7)
    assert not start_compute_request(request, second)
    assert request.started_at == first
    assert request.expires_at == first + timedelta(days=7)

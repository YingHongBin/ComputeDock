from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from computedock_monitor.schemas import SampleInput


def payload(**changes):
    value = {
        "container_name": "worker-01",
        "collected_at": datetime.now(UTC),
        "gpus": [{"gpuid": "GPU-1", "memory_used": 1024, "memory_total": 24576, "utilization": 50}],
    }
    value.update(changes)
    return value


def test_accepts_agent_payload() -> None:
    assert SampleInput.model_validate(payload()).gpus[0].gpuid == "GPU-1"


@pytest.mark.parametrize(
    "gpus",
    [
        [],
        [{"gpuid": "GPU-1", "memory_used": 2, "memory_total": 1, "utilization": 50}],
        [{"gpuid": "GPU-1", "memory_used": 0, "memory_total": 1, "utilization": 101}],
        [
            {"gpuid": "GPU-1", "memory_used": 0, "memory_total": 1, "utilization": 0},
            {"gpuid": "GPU-1", "memory_used": 0, "memory_total": 1, "utilization": 0},
        ],
    ],
)
def test_rejects_invalid_gpu_batch(gpus) -> None:
    with pytest.raises(ValidationError):
        SampleInput.model_validate(payload(gpus=gpus))

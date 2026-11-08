"""Resource approvals are reservations, distinct from container telemetry."""

import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from test_user_auth_flows import login, make_test_app, seed_admin

from computedock_monitor.models import (
    AuditEvent,
    ComputeRequest,
    ComputeResource,
    ContainerInstance,
    Project,
    User,
)
from computedock_monitor.security import utcnow
from computedock_monitor.services import get_or_create_container


@pytest.fixture
def context(monkeypatch):
    client, sessions = make_test_app(monkeypatch)
    admin = seed_admin(sessions)
    headers = {"X-CSRF-Token": login(client, admin.username, "long-enough-admin-password")}
    resource_input = {
        "name": "server",
        "gpu_model": "A100",
        "gpu_count": 4,
        "cpu_cores": 32,
        "memory_gib": 128,
        "default_cpu_cores": 8,
        "default_memory_gib": 32,
    }
    response = client.post("/api/v1/resources", json=resource_input, headers=headers)
    assert response.status_code == 201, response.text
    resource = response.json()
    response = client.post("/api/v1/projects", json={"name": "test squad"}, headers=headers)
    assert response.status_code == 201, response.text
    project = response.json()

    def apply(*, approve=False, **overrides):
        payload = {
            "project_id": project["id"],
            "resource_id": resource["id"],
            "gpu_count": 2,
            "cpu_cores": 24,
            "memory_gib": 96,
            "duration_days": 7,
        }
        payload.update(overrides)
        result = client.post("/api/v1/compute-requests", json=payload, headers=headers)
        assert result.status_code == 201, result.text
        if approve:
            result = client.post(
                f"/api/v1/compute-requests/{result.json()['id']}/review",
                json={"decision": "approved"},
                headers=headers,
            )
            assert result.status_code == 200, result.text
        return result.json()

    return client, sessions, headers, resource, project, apply, resource_input


def configuration(request, **changes):
    return {
        "change_type": "config",
        **{key: request[key] for key in ("gpu_count", "cpu_cores", "memory_gib")},
        **changes,
    }


def card(context):
    client, _, _, resource, *_ = context
    return client.get(f"/api/v1/resources/{resource['id']}").json()


def test_required_integer_capacities_and_defaults(context):
    client, _, headers, resource, project, _, payload = context
    for changes in (
        {"default_cpu_cores": 33},
        {"default_memory_gib": 129},
        {"cpu_cores": 0},
        {"memory_gib": 0},
        {"cpu_cores": 2.5},
        {"memory_gib": True},
    ):
        response = client.put(
            f"/api/v1/resources/{resource['id']}", json={**payload, **changes}, headers=headers
        )
        assert response.status_code == 422
    for missing in ("cpu_cores", "memory_gib", "default_cpu_cores", "default_memory_gib"):
        partial = {k: v for k, v in payload.items() if k != missing}
        assert client.post("/api/v1/resources", json=partial, headers=headers).status_code == 422
    for changes in ({"cpu_cores": 33}, {"memory_gib": 129}, {"cpu_cores": 1.5}):
        body = {
            "project_id": project["id"],
            "resource_id": resource["id"],
            "gpu_count": 1,
            "cpu_cores": 8,
            "memory_gib": 32,
            "duration_days": 7,
        }
        assert (
            client.post(
                "/api/v1/compute-requests", json={**body, **changes}, headers=headers
            ).status_code
            == 422
        )


def test_remaining_counts_approved_unstarted_and_allows_overcommit(context):
    client, sessions, headers, _resource, _, apply, _ = context
    first = apply(approve=True)
    pending = apply()
    apply()  # Pending requests reserve nothing.
    assert card(context)["reserved_cpu_cores"] == 24
    assert card(context)["remaining_cpu_cores"] == 8
    assert card(context)["remaining_memory_gib"] == 32
    # A second approval can exceed remaining capacity but not individual capacity.
    result = client.post(
        f"/api/v1/compute-requests/{pending['id']}/review",
        json={"decision": "approved"},
        headers=headers,
    )
    assert result.status_code == 200
    result = card(context)
    assert result["reserved_cpu_cores"] == 48
    assert result["reserved_memory_gib"] == 192
    assert result["remaining_cpu_cores"] == result["remaining_memory_gib"] == 0
    assert result["allocated_gpu_count"] == 0  # No telemetry yet.
    with sessions() as db:
        request = db.get(ComputeRequest, uuid.UUID(first["id"]))
        request.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert card(context)["reserved_cpu_cores"] == 24
    assert client.get("/api/v1/resources").json()[0]["reserved_cpu_cores"] == 24


@pytest.mark.parametrize(("field", "target"), [("cpu_cores", 12), ("memory_gib", 48)])
def test_configuration_changes_apply_only_on_approval(context, field, target):
    client, sessions, headers, _, _, apply, _ = context
    request = apply(approve=True)
    url = f"/api/v1/compute-requests/{request['id']}"
    # CPU/memory can change after approval, even before first report.
    change = client.post(
        url + "/changes", json=configuration(request, **{field: target}), headers=headers
    )
    assert change.status_code == 201, change.text
    assert change.json()["before_value"][field] == request[field]
    assert change.json()["after_value"][field] == target
    assert card(context)["reserved_" + field] == request[field]
    result = client.post(
        url + f"/changes/{change.json()['id']}/review",
        json={"decision": "approved"},
        headers=headers,
    )
    assert result.status_code == 200
    assert client.get(url).json()[field] == target
    assert card(context)["reserved_" + field] == target
    with sessions() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "compute_change.approved"))
        assert audit.after["after_value"][field] == target
    # Increasing back to the original amount is also supported, without approval side effects.
    change = client.post(
        url + "/changes",
        json=configuration(request),
        headers=headers,
    )
    assert change.status_code == 201
    client.post(
        url + f"/changes/{change.json()['id']}/review",
        json={"decision": "rejected", "comment": "not needed"},
        headers=headers,
    )
    assert card(context)["reserved_" + field] == target


def test_review_rechecks_current_capacity(context):
    client, sessions, headers, resource, _, apply, _ = context
    request = apply()
    with sessions() as db:
        db.get(ComputeResource, uuid.UUID(resource["id"])).cpu_cores = 16
        db.commit()
    response = client.post(
        f"/api/v1/compute-requests/{request['id']}/review",
        json={"decision": "approved"},
        headers=headers,
    )
    assert response.status_code == 409
    assert card(context)["reserved_cpu_cores"] == 0


def test_change_review_rechecks_capacity_and_enforces_positive_target(context):
    client, sessions, headers, resource, _, apply, _ = context
    request = apply(approve=True, cpu_cores=8)
    url = f"/api/v1/compute-requests/{request['id']}"
    for amount in (0, -1, 33, 8):
        assert (
            client.post(
                url + "/changes", json=configuration(request, cpu_cores=amount), headers=headers
            ).status_code
            == 422
        )
    change = client.post(
        url + "/changes", json=configuration(request, cpu_cores=24), headers=headers
    ).json()
    with sessions() as db:
        db.get(ComputeResource, uuid.UUID(resource["id"])).cpu_cores = 16
        db.commit()
    assert (
        client.post(
            url + f"/changes/{change['id']}/review", json={"decision": "approved"}, headers=headers
        ).status_code
        == 409
    )
    assert card(context)["reserved_cpu_cores"] == 8


def test_token_lookup_and_single_container_rebuild(context):
    client, sessions, headers, resource, _, apply, _ = context
    request = apply(approve=True)
    auth = {"Authorization": "Bearer " + request["token"]}
    url = "/api/v1/agent/allocation"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer invalid"}).status_code == 401
    response = client.get(url, headers=auth)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["cpu_cores"] == 24
    assert response.json()["memory_gib"] == 96
    with sessions() as db:
        item = db.get(ComputeRequest, uuid.UUID(request["id"]))
        assert item.started_at is None and item.expires_at is None
        server = db.get(ComputeResource, item.resource_id)
        now = utcnow()
        container = get_or_create_container(db, server, item, "training", now, now)
        container_id = container.id
        item.started_at = now
        item.expires_at = now + timedelta(days=7)
        expiry = item.expires_at
        db.commit()
        assert get_or_create_container(db, server, item, "training", now, now).id == container_id
        with pytest.raises(HTTPException) as error:
            get_or_create_container(db, server, item, "second", now, now)
        assert error.value.status_code == 409
    response = client.get(url, headers=auth)
    assert response.status_code == 409
    assert "training" in response.json()["detail"]
    client.delete(f"/api/v1/resources/{resource['id']}/containers/{container_id}", headers=headers)
    assert client.get(url, headers=auth).status_code == 200
    with sessions() as db:
        item = db.get(ComputeRequest, uuid.UUID(request["id"]))
        assert item.expires_at.replace(tzinfo=expiry.tzinfo) == expiry
        item.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get(url, headers=auth).status_code == 409


@pytest.mark.parametrize("disabled", ["resource", "applicant", "project"])
def test_lookup_blocks_disabled_relations(context, disabled):
    client, sessions, _, resource, project, apply, _ = context
    request = apply(approve=True)
    with sessions() as db:
        if disabled == "resource":
            db.get(ComputeResource, uuid.UUID(resource["id"])).disabled_at = utcnow()
        elif disabled == "project":
            db.get(Project, uuid.UUID(project["id"])).status = "disabled"
        else:
            db.get(User, uuid.UUID(request["applicant_id"])).status = "disabled"
        db.commit()
    assert (
        client.get(
            "/api/v1/agent/allocation", headers={"Authorization": "Bearer " + request["token"]}
        ).status_code
        == 409
    )


def test_database_prevents_two_active_containers(context):
    _, sessions, _, _, _, apply, _ = context
    request = apply(approve=True)
    now = utcnow()
    with sessions() as db:
        for name in ("first", "second"):
            db.add(
                ContainerInstance(
                    resource_id=uuid.UUID(request["resource_id"]),
                    compute_request_id=uuid.UUID(request["id"]),
                    name=name,
                    generation=1,
                    first_reported_at=now,
                    last_received_at=now,
                    latest_collected_at=now,
                    current_gpu_ids=[],
                )
            )
        with pytest.raises(IntegrityError):
            db.flush()


def test_zero_gpu_request_reports_heartbeat_and_can_expand_release(context):
    from computedock_monitor.models import SampleBatch

    client, sessions, headers, _, project, apply, _ = context
    request = apply(approve=True, gpu_count=0)
    auth = {"Authorization": "Bearer " + request["token"]}
    assert client.get("/api/v1/agent/allocation", headers=auth).json()["gpu_count"] == 0
    assert card(context)["reserved_gpu_count"] == 0
    assert card(context)["reserved_cpu_cores"] == 24
    SampleBatch.__table__.create(sessions.kw["bind"])
    payload = {"container_name": "cpu-worker", "collected_at": utcnow().isoformat(), "gpus": []}
    response = client.post("/api/v1/agent/samples", json=payload, headers=auth)
    assert response.status_code == 200, response.text
    assert (
        client.post("/api/v1/agent/samples", json=payload, headers=auth).json()["status"]
        == "duplicate"
    )
    url = f"/api/v1/compute-requests/{request['id']}"
    running = client.get(url).json()
    assert running["runtime_status"] == "running"
    payload["collected_at"] = utcnow().isoformat()
    assert client.post("/api/v1/agent/samples", json=payload, headers=auth).status_code == 200
    assert client.get(url).json()["expires_at"] == running["expires_at"]
    for gpu_count in (1, 0):
        change = client.post(
            url + "/changes", json=configuration(request, gpu_count=gpu_count), headers=headers
        )
        assert change.status_code == 201, change.text
        reviewed = client.post(
            url + f"/changes/{change.json()['id']}/review",
            json={"decision": "approved"},
            headers=headers,
        )
        assert reviewed.status_code == 200, reviewed.text
    assert client.get(url).json()["gpu_count"] == 0
    assert (
        client.post(
            url + "/changes", json=configuration(request, gpu_count=-1), headers=headers
        ).status_code
        == 422
    )
    body = {
        "project_id": project["id"],
        "resource_id": request["resource_id"],
        "gpu_count": -1,
        "cpu_cores": 8,
        "memory_gib": 32,
        "duration_days": 7,
    }
    assert client.post("/api/v1/compute-requests", json=body, headers=headers).status_code == 422


def test_resource_description_is_saved_updated_and_clearable(context):
    client, sessions, headers, resource, _, _, payload = context
    assert resource["description"] == ""
    description = "仅供训练使用\n请先联系管理员 <script>alert(1)</script>"
    created = client.post(
        "/api/v1/resources",
        json={**payload, "name": "documented", "description": description},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    resource_id = created.json()["id"]
    url = f"/api/v1/resources/{resource_id}"
    assert client.get(url).json()["description"] == description
    assert (
        next(r for r in client.get("/api/v1/resources").json() if r["id"] == resource_id)[
            "description"
        ]
        == description
    )
    updated = client.put(
        url, json={**payload, "name": "documented", "description": "新说明"}, headers=headers
    )
    assert updated.status_code == 200
    with sessions() as db:
        assert db.get(ComputeResource, uuid.UUID(resource_id)).description == "新说明"
    assert (
        client.put(
            url, json={**payload, "name": "documented", "description": "x" * 4001}, headers=headers
        ).status_code
        == 422
    )
    cleared = client.put(
        url, json={**payload, "name": "documented", "description": ""}, headers=headers
    )
    assert cleared.json()["description"] == ""


@pytest.mark.parametrize("delta", [3, -2])
def test_time_adjustments_update_expiry_only_after_approval(context, delta):
    client, sessions, headers, _, _, apply, _ = context
    request = apply(approve=True)
    start = utcnow()
    with sessions() as db:
        record = db.get(ComputeRequest, uuid.UUID(request["id"]))
        record.started_at = start
        record.expires_at = start + timedelta(days=7)
        db.commit()
    url = f"/api/v1/compute-requests/{request['id']}"
    original = client.get(url).json()
    change = client.post(
        url + "/changes", json={"change_type": "time", "days_delta": delta}, headers=headers
    )
    assert change.status_code == 201, change.text
    assert change.json()["after_value"] == {"duration_days": 7 + delta}
    assert client.get(url).json()["expires_at"] == original["expires_at"]
    reviewed = client.post(
        url + f"/changes/{change.json()['id']}/review",
        json={"decision": "approved"},
        headers=headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    with sessions() as db:
        record = db.get(ComputeRequest, uuid.UUID(request["id"]))
        assert record.duration_days == 7 + delta
        assert record.expires_at.replace(tzinfo=start.tzinfo) == start + timedelta(days=7 + delta)
        assert record.gpu_count == request["gpu_count"]
        assert record.cpu_cores == request["cpu_cores"]
        assert record.memory_gib == request["memory_gib"]


def test_time_reduction_validated_at_submission_and_review(context):
    client, sessions, headers, _, _, apply, _ = context
    request = apply(approve=True)
    with sessions() as db:
        record = db.get(ComputeRequest, uuid.UUID(request["id"]))
        record.started_at = utcnow()
        record.expires_at = utcnow() + timedelta(days=7)
        db.commit()
    url = f"/api/v1/compute-requests/{request['id']}"
    for delta in (0, -7, -14, 15, -15, 1.5):
        response = client.post(
            url + "/changes", json={"change_type": "time", "days_delta": delta}, headers=headers
        )
        assert response.status_code == 422
    change = client.post(
        url + "/changes", json={"change_type": "time", "days_delta": -2}, headers=headers
    ).json()
    with sessions() as db:
        record = db.get(ComputeRequest, uuid.UUID(request["id"]))
        record.expires_at = utcnow() + timedelta(days=1)
        db.commit()
    reviewed = client.post(
        url + f"/changes/{change['id']}/review", json={"decision": "approved"}, headers=headers
    )
    assert reviewed.status_code == 409
    assert client.get(url).json()["duration_days"] == 7


def test_configuration_is_atomic_and_requires_all_fields(context):
    client, _, headers, _, _, apply, _ = context
    request = apply(approve=True)
    url = f"/api/v1/compute-requests/{request['id']}"
    assert (
        client.post(
            url + "/changes", json={"change_type": "config", "gpu_count": 0}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            url + "/changes", json={**configuration(request), "days_delta": 1}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            url + "/changes", json=configuration(request, cpu_cores=100), headers=headers
        ).status_code
        == 422
    )
    change = client.post(
        url + "/changes",
        json=configuration(request, gpu_count=0, cpu_cores=12, memory_gib=64),
        headers=headers,
    )
    assert change.status_code == 201
    assert (
        client.post(
            url + "/changes", json=configuration(request, cpu_cores=16), headers=headers
        ).status_code
        == 409
    )
    assert client.get(url).json()["gpu_count"] == request["gpu_count"]
    reviewed = client.post(
        url + f"/changes/{change.json()['id']}/review",
        json={"decision": "approved"},
        headers=headers,
    )
    assert reviewed.status_code == 200
    updated = client.get(url).json()
    assert (updated["gpu_count"], updated["cpu_cores"], updated["memory_gib"]) == (0, 12, 64)
    assert updated["duration_days"] == 7

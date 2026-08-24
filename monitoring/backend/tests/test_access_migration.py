from pathlib import Path
from runpy import run_path

from sqlalchemy import CheckConstraint

from computedock_monitor.models import Base

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0001_initial.py"


def test_clean_schema_contains_all_business_tables() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    for table in (
        "users",
        "admin_sessions",
        "registration_requests",
        "email_action_tokens",
        "projects",
        "compute_resources",
        "compute_requests",
        "compute_request_changes",
        "container_instances",
        "sample_batches",
        "gpu_samples",
        "hourly_gpu_rollups",
        "notification_outbox",
        "smtp_settings",
        "system_settings",
        "audit_events",
        "worker_checkpoints",
    ):
        assert f"CREATE TABLE {table}" in content


def test_clean_schema_has_no_legacy_compatibility_structures() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE admins" not in content
    assert "admin_id" not in content
    assert "archived_at" not in content
    assert "uq_container_legacy" not in content
    assert "UPDATE container_instances" not in content
    assert "CREATE TABLE project_members" not in content
    assert "project_members" not in Base.metadata.tables
    resource_section = content.split("CREATE TABLE compute_resources", 1)[1].split(
        "CREATE TABLE compute_requests", 1
    )[0]
    assert "token_hash" not in resource_section
    assert " token " not in resource_section


def test_clean_schema_requires_request_owned_containers_and_rollups() -> None:
    schema_sql = run_path(str(MIGRATION))["SCHEMA_SQL"]
    assert "compute_request_id uuid NOT NULL REFERENCES compute_requests" in schema_sql
    assert "WHERE removed_at IS NULL" in schema_sql


def test_clean_schema_is_the_only_migration() -> None:
    versions = sorted(MIGRATION.parent.glob("*.py"))
    assert [path.name for path in versions] == ["0001_initial.py"]


def test_clean_schema_has_no_check_constraints() -> None:
    schema_sql = run_path(str(MIGRATION))["SCHEMA_SQL"]
    assert "CHECK (" not in schema_sql
    checks = [
        constraint
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert checks == []

from pathlib import Path

from sqlalchemy import CheckConstraint

from computedock_monitor.models import Base

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0002_access_requests.py"


def test_access_migration_preserves_legacy_tokens_and_samples() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    assert "ALTER COLUMN token_hash DROP NOT NULL" in content
    assert "ALTER COLUMN token DROP NOT NULL" in content
    assert "UPDATE compute_resources SET disabled_at = archived_at" in content
    assert "DROP TABLE sample_batches" not in content
    assert "DROP TABLE gpu_samples" not in content


def test_access_migration_adds_permanent_business_records() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    for table in (
        "users",
        "registration_requests",
        "projects",
        "project_members",
        "compute_requests",
        "compute_request_changes",
        "hourly_gpu_rollups",
        "notification_outbox",
        "audit_events",
    ):
        assert f"CREATE TABLE {table}" in content


def test_access_migration_keeps_existing_sessions_compatible() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    assert "ADD COLUMN user_id" in content
    assert "UPDATE admin_sessions SET user_id = admin_id" in content
    assert "ALTER TABLE admin_sessions ALTER COLUMN admin_id DROP NOT NULL" in content


def test_container_namespace_migration_preserves_legacy_and_request_names() -> None:
    migration = MIGRATION.with_name("0003_request_container_scope.py")
    content = migration.read_text(encoding="utf-8")
    assert "uq_container_legacy_active_name" in content
    assert "uq_container_request_active_name" in content
    assert "WHERE compute_request_id IS NULL" in content
    assert "WHERE removed_at IS NULL AND compute_request_id IS NOT NULL" in content


def test_duration_constraint_migration_accepts_legacy_postgres_name() -> None:
    access_content = MIGRATION.read_text(encoding="utf-8")
    scope_content = MIGRATION.with_name("0003_request_container_scope.py").read_text(
        encoding="utf-8"
    )
    assert "CONSTRAINT ck_compute_requests_duration_days" in access_content
    assert "DROP CONSTRAINT IF EXISTS ck_compute_requests_duration_days" in scope_content
    assert "DROP CONSTRAINT IF EXISTS compute_requests_duration_days_check" in scope_content


def test_check_constraint_migration_removes_all_existing_checks() -> None:
    migration = MIGRATION.with_name("0005_drop_check_constraints.py")
    content = migration.read_text(encoding="utf-8")
    for constraint_name in (
        "ck_admin_sessions_principal",
        "compute_request_changes_amount_check",
        "compute_request_changes_approval_status_check",
        "compute_request_changes_change_type_check",
        "ck_compute_requests_duration_days",
        "compute_requests_approval_status_check",
        "compute_requests_gpu_count_check",
        "compute_resources_gpu_count_check",
        "email_action_tokens_purpose_check",
        "gpu_samples_check",
        "gpu_samples_memory_total_check",
        "gpu_samples_utilization_check",
        "hourly_gpu_rollups_online_seconds_check",
        "hourly_gpu_rollups_sample_count_check",
        "notification_outbox_status_check",
        "projects_status_check",
        "registration_requests_status_check",
        "users_role_check",
        "users_status_check",
    ):
        assert constraint_name in content
    assert "DROP CONSTRAINT IF EXISTS" in content


def test_model_metadata_does_not_recreate_check_constraints() -> None:
    checks = [
        constraint
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert checks == []

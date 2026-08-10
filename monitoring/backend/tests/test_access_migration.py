from pathlib import Path
from runpy import run_path

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
        "worker_checkpoints",
    ):
        assert f"CREATE TABLE {table}" in content


def test_project_number_is_internal_and_generated_by_database() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    assert "code varchar(100) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text" in content


def test_access_migration_keeps_existing_sessions_compatible() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    assert "ADD COLUMN user_id" in content
    assert "UPDATE admin_sessions SET user_id = admin_id" in content
    assert "ALTER TABLE admin_sessions ALTER COLUMN admin_id DROP NOT NULL" in content


def test_combined_migration_preserves_legacy_and_request_container_names() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    assert "uq_container_legacy_active_name" in content
    assert "uq_container_request_active_name" in content
    assert "WHERE compute_request_id IS NULL" in content
    assert "WHERE removed_at IS NULL AND compute_request_id IS NOT NULL" in content


def test_combined_migration_creates_no_new_check_constraints() -> None:
    schema_sql = run_path(str(MIGRATION))["SCHEMA_SQL"]
    assert "CHECK (" not in schema_sql


def test_combined_migration_removes_initial_check_constraints() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    for constraint_name in (
        "compute_resources_gpu_count_check",
        "gpu_samples_check",
        "gpu_samples_memory_total_check",
        "gpu_samples_utilization_check",
    ):
        assert constraint_name in content
    assert "DROP CONSTRAINT IF EXISTS" in content


def test_smtp_settings_are_added_in_separate_migration() -> None:
    migration = MIGRATION.with_name("0003_smtp_settings.py")
    content = migration.read_text(encoding="utf-8")
    assert 'down_revision = "0002_access_requests"' in content
    assert "CREATE TABLE smtp_settings" in content
    assert "CREATE TABLE smtp_settings" not in MIGRATION.read_text(encoding="utf-8")


def test_migration_chain_contains_smtp_settings_revision() -> None:
    versions = sorted(MIGRATION.parent.glob("*.py"))
    assert [path.name for path in versions] == [
        "0001_initial.py",
        "0002_access_requests.py",
        "0003_smtp_settings.py",
    ]


def test_model_metadata_does_not_recreate_check_constraints() -> None:
    checks = [
        constraint
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert checks == []

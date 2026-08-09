from pathlib import Path

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

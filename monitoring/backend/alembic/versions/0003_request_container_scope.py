"""Allow cumulative extensions and scope container names to requests."""

from alembic import op

revision = "0003_request_container_scope"
down_revision = "0002_access_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE compute_requests DROP CONSTRAINT ck_compute_requests_duration_days")
    op.execute(
        "ALTER TABLE compute_requests ADD CONSTRAINT ck_compute_requests_duration_days "
        "CHECK (duration_days > 0)"
    )
    op.execute("DROP INDEX IF EXISTS uq_container_active_name")
    op.execute("ALTER TABLE container_instances DROP CONSTRAINT uq_container_generation")
    op.execute(
        "CREATE UNIQUE INDEX uq_container_legacy_generation "
        "ON container_instances(resource_id, name, generation) "
        "WHERE compute_request_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_container_request_generation "
        "ON container_instances(compute_request_id, name, generation) "
        "WHERE compute_request_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_container_legacy_active_name "
        "ON container_instances(resource_id, name) "
        "WHERE removed_at IS NULL AND compute_request_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_container_request_active_name "
        "ON container_instances(compute_request_id, name) "
        "WHERE removed_at IS NULL AND compute_request_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_container_request_active_name")
    op.execute("DROP INDEX IF EXISTS uq_container_legacy_active_name")
    op.execute("DROP INDEX IF EXISTS uq_container_request_generation")
    op.execute("DROP INDEX IF EXISTS uq_container_legacy_generation")
    op.execute(
        "ALTER TABLE container_instances ADD CONSTRAINT uq_container_generation "
        "UNIQUE(resource_id, name, generation)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_container_active_name ON container_instances(resource_id, name) "
        "WHERE removed_at IS NULL"
    )
    op.execute("ALTER TABLE compute_requests DROP CONSTRAINT ck_compute_requests_duration_days")
    op.execute(
        "ALTER TABLE compute_requests ADD CONSTRAINT ck_compute_requests_duration_days "
        "CHECK (duration_days BETWEEN 1 AND 14)"
    )

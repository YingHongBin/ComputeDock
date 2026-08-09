"""Track durable worker progress."""

from alembic import op

revision = "0004_worker_checkpoint"
down_revision = "0003_request_container_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE worker_checkpoints (
            name varchar(100) PRIMARY KEY,
            completed_through date,
            updated_at timestamptz NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS worker_checkpoints")

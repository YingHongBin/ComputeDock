"""Add database-backed API base URL setting."""

from alembic import op

revision = "0004_api_base_url"
down_revision = "0003_smtp_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE system_settings (
            id smallint PRIMARY KEY,
            api_base_url varchar(2048) NOT NULL DEFAULT '',
            updated_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            updated_at timestamptz NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS system_settings")

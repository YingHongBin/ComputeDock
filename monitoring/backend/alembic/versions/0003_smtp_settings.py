"""Add database-backed SMTP settings."""

from alembic import op

revision = "0003_smtp_settings"
down_revision = "0002_access_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE smtp_settings (
            id smallint PRIMARY KEY,
            host varchar(255) NOT NULL DEFAULT '',
            port integer NOT NULL DEFAULT 587,
            username varchar(320) NOT NULL DEFAULT '',
            password text NOT NULL DEFAULT '',
            from_email varchar(320) NOT NULL DEFAULT '',
            from_name varchar(200) NOT NULL DEFAULT 'ComputeDock',
            use_tls boolean NOT NULL DEFAULT true,
            updated_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            updated_at timestamptz NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS smtp_settings")

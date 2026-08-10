"""Add users, projects, compute requests, notifications, and hourly rollups."""

from alembic import op

revision = "0002_access_requests"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


SCHEMA_SQL = r"""
CREATE TABLE users (
    id uuid PRIMARY KEY,
    username varchar(100) NOT NULL UNIQUE,
    full_name varchar(200) NOT NULL,
    email varchar(320) UNIQUE,
    email_verified_at timestamptz,
    password_hash text NOT NULL,
    role varchar(20) NOT NULL CHECK (role IN ('admin', 'user')),
    status varchar(20) NOT NULL CHECK (status IN ('active', 'disabled')),
    must_bind_email boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

INSERT INTO users (
    id, username, full_name, password_hash, role, status, must_bind_email,
    created_at, updated_at
)
SELECT
    id, username, username, password_hash, 'admin', 'active', true,
    created_at, updated_at
FROM admins
ON CONFLICT (id) DO NOTHING;

ALTER TABLE admin_sessions
    ADD COLUMN user_id uuid REFERENCES users(id) ON DELETE CASCADE;
UPDATE admin_sessions SET user_id = admin_id WHERE user_id IS NULL;
ALTER TABLE admin_sessions ALTER COLUMN admin_id DROP NOT NULL;
ALTER TABLE admin_sessions
    ADD CONSTRAINT ck_admin_sessions_principal
    CHECK (admin_id IS NOT NULL OR user_id IS NOT NULL);
CREATE INDEX ix_admin_sessions_user_id ON admin_sessions(user_id);

CREATE TABLE registration_requests (
    id uuid PRIMARY KEY,
    username varchar(100) NOT NULL,
    full_name varchar(200) NOT NULL,
    email varchar(320) NOT NULL,
    password_hash text NOT NULL,
    status varchar(30) NOT NULL
        CHECK (status IN ('email_pending', 'pending', 'approved', 'rejected')),
    email_verified_at timestamptz,
    reviewer_id uuid REFERENCES users(id) ON DELETE RESTRICT,
    review_comment text,
    reviewed_at timestamptz,
    created_user_id uuid REFERENCES users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX ix_registration_requests_status_created
    ON registration_requests(status, created_at);
CREATE UNIQUE INDEX uq_registration_requests_pending_username
    ON registration_requests(lower(username))
    WHERE status IN ('email_pending', 'pending');
CREATE UNIQUE INDEX uq_registration_requests_pending_email
    ON registration_requests(lower(email))
    WHERE status IN ('email_pending', 'pending');

CREATE TABLE email_action_tokens (
    id uuid PRIMARY KEY,
    purpose varchar(40) NOT NULL
        CHECK (purpose IN ('registration_verify', 'password_reset', 'email_change')),
    token_hash bytea NOT NULL UNIQUE,
    user_id uuid REFERENCES users(id) ON DELETE CASCADE,
    registration_request_id uuid REFERENCES registration_requests(id) ON DELETE CASCADE,
    pending_email varchar(320),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL
);
CREATE INDEX ix_email_action_tokens_expiry ON email_action_tokens(expires_at);

CREATE TABLE projects (
    id uuid PRIMARY KEY,
    code varchar(100) NOT NULL UNIQUE,
    name varchar(200) NOT NULL UNIQUE,
    description text NOT NULL DEFAULT '',
    status varchar(20) NOT NULL CHECK (status IN ('active', 'disabled')),
    created_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE project_members (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    added_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL,
    PRIMARY KEY(project_id, user_id)
);
CREATE INDEX ix_project_members_user_id ON project_members(user_id);

ALTER TABLE compute_resources
    ALTER COLUMN token_hash DROP NOT NULL,
    ALTER COLUMN token DROP NOT NULL,
    ADD COLUMN disabled_at timestamptz,
    ADD COLUMN disabled_by_id uuid REFERENCES users(id) ON DELETE RESTRICT;
UPDATE compute_resources SET disabled_at = archived_at WHERE archived_at IS NOT NULL;

CREATE TABLE compute_requests (
    id uuid PRIMARY KEY,
    applicant_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    resource_id uuid NOT NULL REFERENCES compute_resources(id) ON DELETE RESTRICT,
    gpu_count integer NOT NULL CHECK (gpu_count > 0),
    duration_days integer NOT NULL
        CONSTRAINT ck_compute_requests_duration_days CHECK (duration_days BETWEEN 1 AND 14),
    approval_status varchar(20) NOT NULL
        CHECK (approval_status IN ('pending', 'approved', 'rejected')),
    reviewer_id uuid REFERENCES users(id) ON DELETE RESTRICT,
    review_comment text,
    reviewed_at timestamptz,
    token_hash bytea UNIQUE,
    token varchar(100),
    started_at timestamptz,
    expires_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX ix_compute_requests_applicant_created
    ON compute_requests(applicant_id, created_at);
CREATE INDEX ix_compute_requests_project_created
    ON compute_requests(project_id, created_at);
CREATE INDEX ix_compute_requests_resource_status
    ON compute_requests(resource_id, approval_status);

CREATE TABLE compute_request_changes (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES compute_requests(id) ON DELETE RESTRICT,
    requester_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    change_type varchar(20) NOT NULL
        CHECK (change_type IN ('extend', 'expand', 'release')),
    amount integer NOT NULL CHECK (amount > 0),
    approval_status varchar(20) NOT NULL
        CHECK (approval_status IN ('pending', 'approved', 'rejected')),
    before_value integer NOT NULL,
    after_value integer NOT NULL,
    reviewer_id uuid REFERENCES users(id) ON DELETE RESTRICT,
    review_comment text,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX ix_compute_request_changes_request_created
    ON compute_request_changes(request_id, created_at);
CREATE UNIQUE INDEX uq_compute_request_changes_one_pending
    ON compute_request_changes(request_id)
    WHERE approval_status = 'pending';

ALTER TABLE container_instances
    ADD COLUMN compute_request_id uuid REFERENCES compute_requests(id) ON DELETE RESTRICT;
CREATE INDEX ix_container_request_active
    ON container_instances(compute_request_id, removed_at);

CREATE TABLE hourly_gpu_rollups (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    bucket_start timestamptz NOT NULL,
    resource_id uuid NOT NULL REFERENCES compute_resources(id) ON DELETE RESTRICT,
    compute_request_id uuid REFERENCES compute_requests(id) ON DELETE RESTRICT,
    container_id uuid NOT NULL REFERENCES container_instances(id) ON DELETE RESTRICT,
    gpuid varchar(160) NOT NULL,
    utilization_avg double precision NOT NULL,
    utilization_max integer NOT NULL,
    memory_used_avg double precision NOT NULL,
    memory_used_max bigint NOT NULL,
    memory_total bigint NOT NULL,
    online_seconds integer NOT NULL CHECK (online_seconds >= 0),
    sample_count integer NOT NULL CHECK (sample_count > 0),
    first_collected_at timestamptz NOT NULL,
    last_collected_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT uq_hourly_gpu_rollup_identity
        UNIQUE(container_id, gpuid, bucket_start)
);
CREATE INDEX ix_hourly_rollups_resource_time
    ON hourly_gpu_rollups(resource_id, bucket_start);
CREATE INDEX ix_hourly_rollups_request_time
    ON hourly_gpu_rollups(compute_request_id, bucket_start);
CREATE INDEX ix_hourly_rollups_container_time
    ON hourly_gpu_rollups(container_id, bucket_start);

CREATE TABLE notification_outbox (
    id uuid PRIMARY KEY,
    idempotency_key varchar(240) NOT NULL UNIQUE,
    template varchar(80) NOT NULL,
    to_address varchar(320) NOT NULL,
    cc_addresses jsonb NOT NULL DEFAULT '[]'::jsonb,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status varchar(20) NOT NULL
        CHECK (status IN ('pending', 'sending', 'sent', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL,
    sent_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX ix_notification_outbox_delivery
    ON notification_outbox(status, available_at);

CREATE TABLE audit_events (
    id uuid PRIMARY KEY,
    actor_id uuid REFERENCES users(id) ON DELETE RESTRICT,
    action varchar(100) NOT NULL,
    object_type varchar(100) NOT NULL,
    object_id varchar(100) NOT NULL,
    before jsonb,
    after jsonb,
    created_at timestamptz NOT NULL
);
CREATE INDEX ix_audit_events_object
    ON audit_events(object_type, object_id, created_at);
CREATE INDEX ix_audit_events_actor_created
    ON audit_events(actor_id, created_at);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_events")
    op.execute("DROP TABLE IF EXISTS notification_outbox")
    op.execute("DROP TABLE IF EXISTS hourly_gpu_rollups")
    op.execute("ALTER TABLE container_instances DROP COLUMN IF EXISTS compute_request_id")
    op.execute("DROP TABLE IF EXISTS compute_request_changes")
    op.execute("DROP TABLE IF EXISTS compute_requests")
    op.execute("ALTER TABLE compute_resources DROP COLUMN IF EXISTS disabled_by_id")
    op.execute("ALTER TABLE compute_resources DROP COLUMN IF EXISTS disabled_at")
    op.execute("ALTER TABLE compute_resources ALTER COLUMN token SET NOT NULL")
    op.execute("ALTER TABLE compute_resources ALTER COLUMN token_hash SET NOT NULL")
    op.execute("DROP TABLE IF EXISTS project_members")
    op.execute("DROP TABLE IF EXISTS projects")
    op.execute("DROP TABLE IF EXISTS email_action_tokens")
    op.execute("DROP TABLE IF EXISTS registration_requests")
    op.execute("ALTER TABLE admin_sessions DROP CONSTRAINT IF EXISTS ck_admin_sessions_principal")
    op.execute("ALTER TABLE admin_sessions DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE admin_sessions ALTER COLUMN admin_id SET NOT NULL")
    op.execute("DROP TABLE IF EXISTS users")

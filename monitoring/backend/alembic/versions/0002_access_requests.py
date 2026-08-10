"""Upgrade the initial monitoring schema to the access-management release."""

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
    role varchar(20) NOT NULL,
    status varchar(20) NOT NULL,
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
CREATE INDEX ix_admin_sessions_user_id ON admin_sessions(user_id);

CREATE TABLE registration_requests (
    id uuid PRIMARY KEY,
    username varchar(100) NOT NULL,
    full_name varchar(200) NOT NULL,
    email varchar(320) NOT NULL,
    password_hash text NOT NULL,
    status varchar(30) NOT NULL,
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
    purpose varchar(40) NOT NULL,
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
    status varchar(20) NOT NULL,
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
ALTER TABLE compute_resources
    DROP CONSTRAINT IF EXISTS compute_resources_gpu_count_check,
    DROP CONSTRAINT IF EXISTS ck_compute_resources_gpu_count_positive;
ALTER TABLE gpu_samples
    DROP CONSTRAINT IF EXISTS gpu_samples_check,
    DROP CONSTRAINT IF EXISTS ck_gpu_samples_memory_used,
    DROP CONSTRAINT IF EXISTS gpu_samples_memory_total_check,
    DROP CONSTRAINT IF EXISTS ck_gpu_samples_memory_total,
    DROP CONSTRAINT IF EXISTS gpu_samples_utilization_check,
    DROP CONSTRAINT IF EXISTS ck_gpu_samples_utilization;

CREATE TABLE compute_requests (
    id uuid PRIMARY KEY,
    applicant_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    resource_id uuid NOT NULL REFERENCES compute_resources(id) ON DELETE RESTRICT,
    gpu_count integer NOT NULL,
    duration_days integer NOT NULL,
    approval_status varchar(20) NOT NULL,
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
    change_type varchar(20) NOT NULL,
    amount integer NOT NULL,
    approval_status varchar(20) NOT NULL,
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
DROP INDEX IF EXISTS uq_container_active_name;
ALTER TABLE container_instances DROP CONSTRAINT IF EXISTS uq_container_generation;
CREATE UNIQUE INDEX uq_container_legacy_generation
    ON container_instances(resource_id, name, generation)
    WHERE compute_request_id IS NULL;
CREATE UNIQUE INDEX uq_container_request_generation
    ON container_instances(compute_request_id, name, generation)
    WHERE compute_request_id IS NOT NULL;
CREATE UNIQUE INDEX uq_container_legacy_active_name
    ON container_instances(resource_id, name)
    WHERE removed_at IS NULL AND compute_request_id IS NULL;
CREATE UNIQUE INDEX uq_container_request_active_name
    ON container_instances(compute_request_id, name)
    WHERE removed_at IS NULL AND compute_request_id IS NOT NULL;
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
    online_seconds integer NOT NULL,
    sample_count integer NOT NULL,
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
    status varchar(20) NOT NULL,
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

CREATE TABLE worker_checkpoints (
    name varchar(100) PRIMARY KEY,
    completed_through date,
    updated_at timestamptz NOT NULL
);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS worker_checkpoints")
    op.execute("DROP TABLE IF EXISTS audit_events")
    op.execute("DROP TABLE IF EXISTS notification_outbox")
    op.execute("DROP TABLE IF EXISTS hourly_gpu_rollups")
    op.execute("DROP INDEX IF EXISTS uq_container_request_active_name")
    op.execute("DROP INDEX IF EXISTS uq_container_legacy_active_name")
    op.execute("DROP INDEX IF EXISTS uq_container_request_generation")
    op.execute("DROP INDEX IF EXISTS uq_container_legacy_generation")
    op.execute(
        "ALTER TABLE container_instances ADD CONSTRAINT uq_container_generation "
        "UNIQUE(resource_id, name, generation)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_container_active_name "
        "ON container_instances(resource_id, name) WHERE removed_at IS NULL"
    )
    op.execute("ALTER TABLE container_instances DROP COLUMN IF EXISTS compute_request_id")
    op.execute("DROP TABLE IF EXISTS compute_request_changes")
    op.execute("DROP TABLE IF EXISTS compute_requests")
    op.execute("ALTER TABLE compute_resources DROP COLUMN IF EXISTS disabled_by_id")
    op.execute("ALTER TABLE compute_resources DROP COLUMN IF EXISTS disabled_at")
    op.execute("ALTER TABLE compute_resources ALTER COLUMN token SET NOT NULL")
    op.execute("ALTER TABLE compute_resources ALTER COLUMN token_hash SET NOT NULL")
    op.execute(
        "ALTER TABLE compute_resources ADD CONSTRAINT compute_resources_gpu_count_check "
        "CHECK (gpu_count > 0)"
    )
    op.execute("DROP TABLE IF EXISTS project_members")
    op.execute("DROP TABLE IF EXISTS projects")
    op.execute("DROP TABLE IF EXISTS email_action_tokens")
    op.execute("DROP TABLE IF EXISTS registration_requests")
    op.execute("ALTER TABLE admin_sessions DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE admin_sessions ALTER COLUMN admin_id SET NOT NULL")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute(
        "ALTER TABLE gpu_samples ADD CONSTRAINT gpu_samples_check "
        "CHECK (memory_used >= 0 AND memory_used <= memory_total)"
    )
    op.execute(
        "ALTER TABLE gpu_samples ADD CONSTRAINT gpu_samples_memory_total_check "
        "CHECK (memory_total > 0)"
    )
    op.execute(
        "ALTER TABLE gpu_samples ADD CONSTRAINT gpu_samples_utilization_check "
        "CHECK (utilization >= 0 AND utilization <= 100)"
    )

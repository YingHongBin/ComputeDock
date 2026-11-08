"""Create the clean ComputeDock monitoring schema."""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA_SQL = r"""
SET TIME ZONE 'UTC';

CREATE SCHEMA IF NOT EXISTS partman;
CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman;

CREATE TABLE users (
    id uuid PRIMARY KEY,
    username varchar(100) NOT NULL UNIQUE,
    full_name varchar(200) NOT NULL,
    email varchar(320) NOT NULL UNIQUE,
    email_verified_at timestamptz,
    password_hash text NOT NULL,
    role varchar(20) NOT NULL,
    status varchar(20) NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE admin_sessions (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash bytea NOT NULL UNIQUE,
    csrf_hash bytea NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE INDEX ix_admin_sessions_user_id ON admin_sessions(user_id);
CREATE INDEX ix_admin_sessions_expires_at ON admin_sessions(expires_at);

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

CREATE TABLE compute_resources (
    id uuid PRIMARY KEY,
    name varchar(200) NOT NULL UNIQUE,
    gpu_model varchar(200) NOT NULL,
    default_cpu_cores integer NOT NULL,
    default_memory_gib integer NOT NULL,
    gpu_count integer NOT NULL,
    cpu_cores integer NOT NULL,
    memory_gib integer NOT NULL,
    disabled_at timestamptz,
    disabled_by_id uuid REFERENCES users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE compute_requests (
    id uuid PRIMARY KEY,
    applicant_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    resource_id uuid NOT NULL REFERENCES compute_resources(id) ON DELETE RESTRICT,
    gpu_count integer NOT NULL,
    cpu_cores integer NOT NULL,
    memory_gib integer NOT NULL,
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

CREATE TABLE container_instances (
    id uuid PRIMARY KEY,
    resource_id uuid NOT NULL REFERENCES compute_resources(id) ON DELETE RESTRICT,
    compute_request_id uuid NOT NULL REFERENCES compute_requests(id) ON DELETE RESTRICT,
    name varchar(255) NOT NULL,
    generation integer NOT NULL,
    first_reported_at timestamptz NOT NULL,
    last_received_at timestamptz NOT NULL,
    latest_collected_at timestamptz NOT NULL,
    current_gpu_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    removed_at timestamptz,
    usage_summary_status varchar(20),
    usage_duration_seconds bigint,
    usage_gpu_count integer,
    usage_gpu_utilization_avg double precision,
    usage_gpu_utilization_max integer,
    usage_memory_utilization_avg double precision,
    usage_memory_utilization_max double precision,
    usage_summary_completed_at timestamptz
);
CREATE UNIQUE INDEX uq_container_request_generation
    ON container_instances(compute_request_id, name, generation);
CREATE UNIQUE INDEX uq_container_request_active
    ON container_instances(compute_request_id)
    WHERE removed_at IS NULL;
CREATE INDEX ix_container_resource_active
    ON container_instances(resource_id, removed_at);
CREATE INDEX ix_container_request_active
    ON container_instances(compute_request_id, removed_at);
CREATE INDEX ix_container_usage_summary
    ON container_instances(usage_summary_status, removed_at);

CREATE TABLE sample_batches (
    id uuid NOT NULL,
    container_id uuid NOT NULL REFERENCES container_instances(id) ON DELETE RESTRICT,
    collected_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    payload_hash bytea NOT NULL,
    PRIMARY KEY(id, collected_at),
    CONSTRAINT uq_batch_container_collected UNIQUE(container_id, collected_at)
) PARTITION BY RANGE(collected_at);

CREATE TABLE gpu_samples (
    id bigint GENERATED BY DEFAULT AS IDENTITY,
    collected_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    batch_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    container_id uuid NOT NULL,
    gpuid varchar(160) NOT NULL,
    memory_used bigint NOT NULL,
    memory_total bigint NOT NULL,
    utilization integer NOT NULL,
    PRIMARY KEY(id, collected_at),
    CONSTRAINT uq_gpu_sample_identity UNIQUE(container_id, gpuid, collected_at)
) PARTITION BY RANGE(collected_at);
CREATE INDEX ix_gpu_samples_container_time ON gpu_samples(container_id, collected_at);
CREATE INDEX ix_gpu_samples_resource_time ON gpu_samples(resource_id, collected_at);

CREATE TABLE hourly_gpu_rollups (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    bucket_start timestamptz NOT NULL,
    resource_id uuid NOT NULL REFERENCES compute_resources(id) ON DELETE RESTRICT,
    compute_request_id uuid NOT NULL REFERENCES compute_requests(id) ON DELETE RESTRICT,
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
);

CREATE TABLE system_settings (
    id smallint PRIMARY KEY,
    api_base_url varchar(2048) NOT NULL DEFAULT '',
    low_utilization_warning_enabled boolean NOT NULL DEFAULT true,
    low_utilization_threshold integer NOT NULL DEFAULT 10,
    updated_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    updated_at timestamptz NOT NULL
);

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

SELECT partman.create_partition(
    p_parent_table := 'public.sample_batches',
    p_control := 'collected_at',
    p_interval := '1 day',
    p_premake := 7,
    p_jobmon := false
);
SELECT partman.create_partition(
    p_parent_table := 'public.gpu_samples',
    p_control := 'collected_at',
    p_interval := '1 day',
    p_premake := 7,
    p_jobmon := false
);
UPDATE partman.part_config
SET retention = '30 days',
    retention_keep_table = false,
    retention_keep_index = false,
    infinite_time_partitions = true,
    automatic_maintenance = 'on'
WHERE parent_table IN ('public.sample_batches', 'public.gpu_samples');
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    for table in (
        "worker_checkpoints",
        "audit_events",
        "system_settings",
        "smtp_settings",
        "notification_outbox",
        "hourly_gpu_rollups",
        "gpu_samples",
        "sample_batches",
        "container_instances",
        "compute_request_changes",
        "compute_requests",
        "compute_resources",
        "projects",
        "email_action_tokens",
        "registration_requests",
        "admin_sessions",
        "users",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

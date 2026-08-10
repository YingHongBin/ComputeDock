"""Remove database CHECK constraints.

Business validation remains in the application layer.  Each entry includes the
name produced by the SQL migrations and, where different, the name previously
used by SQLAlchemy metadata so stamped legacy databases are handled as well.
"""

from alembic import op

revision = "0005_drop_check_constraints"
down_revision = "0004_worker_checkpoint"
branch_labels = None
depends_on = None


CHECK_CONSTRAINTS = (
    ("admin_sessions", "ck_admin_sessions_principal"),
    ("compute_request_changes", "compute_request_changes_amount_check"),
    ("compute_request_changes", "ck_compute_request_changes_amount"),
    ("compute_request_changes", "compute_request_changes_approval_status_check"),
    ("compute_request_changes", "ck_compute_request_changes_status"),
    ("compute_request_changes", "compute_request_changes_change_type_check"),
    ("compute_request_changes", "ck_compute_request_changes_type"),
    ("compute_requests", "ck_compute_requests_duration_days"),
    ("compute_requests", "compute_requests_approval_status_check"),
    ("compute_requests", "ck_compute_requests_approval_status"),
    ("compute_requests", "compute_requests_gpu_count_check"),
    ("compute_requests", "ck_compute_requests_gpu_count"),
    ("compute_resources", "compute_resources_gpu_count_check"),
    ("compute_resources", "ck_compute_resources_gpu_count_positive"),
    ("email_action_tokens", "email_action_tokens_purpose_check"),
    ("email_action_tokens", "ck_email_action_tokens_purpose"),
    ("gpu_samples", "gpu_samples_check"),
    ("gpu_samples", "ck_gpu_samples_memory_used"),
    ("gpu_samples", "gpu_samples_memory_total_check"),
    ("gpu_samples", "ck_gpu_samples_memory_total"),
    ("gpu_samples", "gpu_samples_utilization_check"),
    ("gpu_samples", "ck_gpu_samples_utilization"),
    ("hourly_gpu_rollups", "hourly_gpu_rollups_online_seconds_check"),
    ("hourly_gpu_rollups", "ck_hourly_gpu_rollups_online_seconds"),
    ("hourly_gpu_rollups", "hourly_gpu_rollups_sample_count_check"),
    ("hourly_gpu_rollups", "ck_hourly_gpu_rollups_sample_count"),
    ("notification_outbox", "notification_outbox_status_check"),
    ("notification_outbox", "ck_notification_outbox_status"),
    ("projects", "projects_status_check"),
    ("projects", "ck_projects_status"),
    ("registration_requests", "registration_requests_status_check"),
    ("registration_requests", "ck_registration_requests_status"),
    ("users", "users_role_check"),
    ("users", "ck_users_role"),
    ("users", "users_status_check"),
    ("users", "ck_users_status"),
)


RESTORE_CONSTRAINTS = (
    (
        "admin_sessions",
        "ck_admin_sessions_principal",
        "admin_id IS NOT NULL OR user_id IS NOT NULL",
    ),
    ("compute_request_changes", "compute_request_changes_amount_check", "amount > 0"),
    (
        "compute_request_changes",
        "compute_request_changes_approval_status_check",
        "approval_status IN ('pending', 'approved', 'rejected')",
    ),
    (
        "compute_request_changes",
        "compute_request_changes_change_type_check",
        "change_type IN ('extend', 'expand', 'release')",
    ),
    ("compute_requests", "ck_compute_requests_duration_days", "duration_days > 0"),
    (
        "compute_requests",
        "compute_requests_approval_status_check",
        "approval_status IN ('pending', 'approved', 'rejected')",
    ),
    ("compute_requests", "compute_requests_gpu_count_check", "gpu_count > 0"),
    ("compute_resources", "compute_resources_gpu_count_check", "gpu_count > 0"),
    (
        "email_action_tokens",
        "email_action_tokens_purpose_check",
        "purpose IN ('registration_verify', 'password_reset', 'email_change')",
    ),
    (
        "gpu_samples",
        "gpu_samples_check",
        "memory_used >= 0 AND memory_used <= memory_total",
    ),
    ("gpu_samples", "gpu_samples_memory_total_check", "memory_total > 0"),
    (
        "gpu_samples",
        "gpu_samples_utilization_check",
        "utilization >= 0 AND utilization <= 100",
    ),
    (
        "hourly_gpu_rollups",
        "hourly_gpu_rollups_online_seconds_check",
        "online_seconds >= 0",
    ),
    (
        "hourly_gpu_rollups",
        "hourly_gpu_rollups_sample_count_check",
        "sample_count > 0",
    ),
    (
        "notification_outbox",
        "notification_outbox_status_check",
        "status IN ('pending', 'sending', 'sent', 'failed')",
    ),
    ("projects", "projects_status_check", "status IN ('active', 'disabled')"),
    (
        "registration_requests",
        "registration_requests_status_check",
        "status IN ('email_pending', 'pending', 'approved', 'rejected')",
    ),
    ("users", "users_role_check", "role IN ('admin', 'user')"),
    ("users", "users_status_check", "status IN ('active', 'disabled')"),
)


def upgrade() -> None:
    for table_name, constraint_name in CHECK_CONSTRAINTS:
        op.execute(
            f'ALTER TABLE "{table_name}" '
            f'DROP CONSTRAINT IF EXISTS "{constraint_name}"'
        )


def downgrade() -> None:
    for table_name, constraint_name, expression in RESTORE_CONSTRAINTS:
        op.execute(
            f'ALTER TABLE "{table_name}" ADD CONSTRAINT "{constraint_name}" '
            f"CHECK ({expression})"
        )

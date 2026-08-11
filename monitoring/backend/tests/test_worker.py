from datetime import UTC, date, datetime

from computedock_monitor.models import NotificationOutbox
from computedock_monitor.worker import ROLLUP_SQL, day_window, render_notification


def test_business_day_uses_shanghai_midnight() -> None:
    start, end = day_window(date(2026, 8, 10), "Asia/Shanghai")
    assert start == datetime(2026, 8, 9, 16, tzinfo=UTC)
    assert end == datetime(2026, 8, 10, 16, tzinfo=UTC)


def test_rollup_sql_is_hourly_and_idempotent() -> None:
    assert "date_trunc('hour'" in ROLLUP_SQL
    assert "ON CONFLICT (container_id, gpuid, bucket_start) DO UPDATE" in ROLLUP_SQL
    assert "make_interval(secs => :offline_seconds)" in ROLLUP_SQL


def test_notification_renderer_includes_action_link() -> None:
    notification = NotificationOutbox(
        template="password_reset",
        to_address="user@example.test",
        cc_addresses=[],
        payload={
            "full_name": "Test User",
            "action_url": "https://monitor.example.test/reset-password?token=secret",
        },
    )
    subject, body = render_notification(notification)
    assert subject == "重置您的 ComputeDock 密码"
    assert "https://monitor.example.test/reset-password?token=secret" in body


def test_compute_request_admin_notice_includes_applicant_details() -> None:
    notification = NotificationOutbox(
        template="compute_request_pending_admin",
        to_address="admin@example.test",
        cc_addresses=[],
        payload={
            "applicant_name": "GPU Applicant",
            "project_name": "GPU Project",
            "resource_name": "H100 Cluster",
            "gpu_count": 2,
            "duration_days": 7,
        },
    )

    subject, body = render_notification(notification)

    assert subject == "有新的算力申请待审核"
    assert "您好，管理员：" in body
    assert "申请人姓名：GPU Applicant" in body
    assert "项目：GPU Project" in body
    assert "算力资源：H100 Cluster" in body
    assert "GPU 数量：2" in body
    assert "使用天数：7" in body

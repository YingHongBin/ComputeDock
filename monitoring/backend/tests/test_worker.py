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

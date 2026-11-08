from datetime import UTC, date, datetime

from computedock_monitor.config import Settings
from computedock_monitor.models import NotificationOutbox
from computedock_monitor.worker import (
    ROLLUP_SQL,
    aggregation_cutoff_day,
    day_window,
    render_notification,
    warning_target_day,
)


def worker_settings() -> Settings:
    return Settings(
        database_url="sqlite://",
        admin_username="admin",
        admin_password="long-enough-test-password",
        admin_full_name="Administrator",
        admin_email="admin@example.test",
        business_timezone="Asia/Shanghai",
    )


def test_business_day_uses_shanghai_midnight() -> None:
    start, end = day_window(date(2026, 8, 10), "Asia/Shanghai")
    assert start == datetime(2026, 8, 9, 16, tzinfo=UTC)
    assert end == datetime(2026, 8, 10, 16, tzinfo=UTC)


def test_rollup_sql_is_hourly_and_idempotent() -> None:
    assert "date_trunc('hour'" in ROLLUP_SQL
    assert "ON CONFLICT (container_id, gpuid, bucket_start) DO UPDATE" in ROLLUP_SQL
    assert "make_interval(secs => :offline_seconds)" in ROLLUP_SQL
    assert "SUM(utilization * observed_seconds)" in ROLLUP_SQL


def test_daily_jobs_wait_until_eight_in_business_timezone() -> None:
    settings = worker_settings()
    before_eight = datetime(2026, 8, 10, 23, 59, tzinfo=UTC)  # 07:59 in Shanghai
    at_eight = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)  # 08:00 in Shanghai
    assert aggregation_cutoff_day(settings, before_eight) == date(2026, 8, 9)
    assert warning_target_day(settings, before_eight) is None
    assert aggregation_cutoff_day(settings, at_eight) == date(2026, 8, 10)
    assert warning_target_day(settings, at_eight) == date(2026, 8, 10)


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
            "cpu_cores": 8,
            "memory_gib": 32,
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
    assert "Squad：GPU Project" in body
    assert "算力资源：H100 Cluster" in body
    assert "CPU 核心数：8" in body
    assert "内存（GiB）：32" in body
    assert "GPU 数量：2" in body
    assert "使用天数：7" in body


def test_low_utilization_warning_lists_grouped_containers() -> None:
    notification = NotificationOutbox(
        template="low_utilization_warning",
        to_address="user@example.test",
        cc_addresses=["admin@example.test"],
        payload={
            "full_name": "Test User",
            "applicant_name": "Test User",
            "project_name": "Project One",
            "resource_name": "H100 Cluster",
            "approved_gpu_count": 4,
            "statistics_date": "2026-08-10",
            "threshold": 10,
            "request_expired": True,
            "containers": [
                {
                    "name": "training-a",
                    "usage_rate": 3.456,
                    "gpu_count": 2,
                    "first_reported_at": "2026-08-10 00:01:00",
                    "last_reported_at": "2026-08-10 23:59:00",
                },
                {
                    "name": "training-b",
                    "usage_rate": 8.0,
                    "gpu_count": 2,
                    "first_reported_at": "2026-08-10 01:00:00",
                    "last_reported_at": "2026-08-10 20:00:00",
                },
            ],
        },
    )

    subject, body = render_notification(notification)

    assert subject == "算力容器 GPU 使用率过低预警"
    assert "Squad：Project One" in body
    assert "申请状态：已到期" in body
    assert "training-a：平均 GPU 使用率 3.46%" in body
    assert "training-b：平均 GPU 使用率 8.00%" in body


def test_configuration_notice_formats_before_and_after_values() -> None:
    notice = NotificationOutbox(
        template="compute_change_pending_admin",
        to_address="admin@example.test",
        cc_addresses=[],
        payload={
            "applicant_name": "Applicant",
            "change_type": "配置调整",
            "days_delta": None,
            "before_value": {"gpu_count": 2, "cpu_cores": 8, "memory_gib": 32},
            "after_value": {"gpu_count": 0, "cpu_cores": 16, "memory_gib": 64},
        },
    )
    _, body = render_notification(notice)
    assert "调整前：GPU 2 张 / CPU 8 核 / 内存 32 GiB" in body
    assert "调整后：GPU 0 张 / CPU 16 核 / 内存 64 GiB" in body

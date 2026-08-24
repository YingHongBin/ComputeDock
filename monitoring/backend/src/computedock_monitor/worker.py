from __future__ import annotations

import argparse
import smtplib
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from .auditing import record_audit
from .config import Settings, get_settings
from .database import SessionLocal
from .models import (
    ComputeRequest,
    ComputeRequestChange,
    ComputeResource,
    ContainerInstance,
    GpuSample,
    HourlyGpuRollup,
    NotificationOutbox,
    Project,
    SystemSetting,
    User,
    WorkerCheckpoint,
)
from .notifications import active_admin_emails, enqueue_notification
from .security import as_utc, utcnow
from .smtp import SmtpConnectionSettings, effective_smtp_settings, send_email

AUTO_REJECTION_REASONS = {
    "关联用户已禁用",
    "关联项目已禁用",
    "关联算力资源已禁用",
    "原申请已到期",
}

MAIL_SUBJECTS = {
    "registration_verify": "验证您的 ComputeDock 邮箱",
    "registration_pending_admin": "有新的用户注册申请待审核",
    "registration_approved": "ComputeDock 注册申请已通过",
    "registration_rejected": "ComputeDock 注册申请已拒绝",
    "password_reset": "重置您的 ComputeDock 密码",
    "password_changed": "ComputeDock 密码已修改",
    "email_change_verify": "验证您的新邮箱",
    "email_changed": "ComputeDock 绑定邮箱已变更",
    "compute_request_pending_admin": "有新的算力申请待审核",
    "compute_request_approved": "算力申请已通过",
    "compute_request_rejected": "算力申请已拒绝",
    "compute_change_pending_admin": "有新的算力变更申请待审核",
    "compute_change_approved": "算力变更申请已通过",
    "compute_change_rejected": "算力变更申请已拒绝",
    "compute_request_expiring": "算力申请将在一天内到期",
    "compute_request_expired": "算力申请已到期",
    "low_utilization_warning": "算力容器 GPU 使用率过低预警",
}

WARNING_HOUR = 8
MINIMUM_WARNING_SPAN = timedelta(hours=12)
USAGE_SUMMARY_BATCH_SIZE = 100


def render_notification(notification: NotificationOutbox) -> tuple[str, str]:
    subject = MAIL_SUBJECTS.get(notification.template, "ComputeDock 通知")
    payload = notification.payload
    if notification.template == "low_utilization_warning":
        recipient_name = payload.get("full_name") or "管理员"
        lines = [f"您好，{recipient_name}：", "", subject]
        for key, label in (
            ("applicant_name", "申请人姓名"),
            ("project_name", "项目"),
            ("resource_name", "算力资源"),
            ("approved_gpu_count", "申请 GPU 数量"),
            ("statistics_date", "统计日期"),
            ("threshold", "预警阈值"),
        ):
            value = payload.get(key)
            if value not in (None, ""):
                suffix = "%" if key == "threshold" else ""
                lines.append(f"{label}：{value}{suffix}")
        if payload.get("request_expired"):
            lines.append("申请状态：已到期（运行中容器仍继续监控）")
        lines.extend(["", "低使用率容器："])
        for container in payload.get("containers", []):
            if not isinstance(container, dict):
                continue
            lines.append(
                "- {name}：平均 GPU 使用率 {usage_rate:.2f}%，实际 GPU {gpu_count} 张，"
                "上报范围 {first_reported_at} 至 {last_reported_at}".format(
                    name=container.get("name", "--"),
                    usage_rate=float(container.get("usage_rate", 0)),
                    gpu_count=container.get("gpu_count", 0),
                    first_reported_at=container.get("first_reported_at", "--"),
                    last_reported_at=container.get("last_reported_at", "--"),
                )
            )
        lines.extend(
            [
                "",
                "请及时使用已申请的算力资源；如暂时不再需要，请联系管理员释放资源。",
                "",
                "此邮件由 ComputeDock 自动发送。",
            ]
        )
        return subject, "\n".join(lines)
    recipient_name = (
        "管理员"
        if notification.template == "compute_request_pending_admin"
        else payload.get("full_name") or payload.get("applicant_name") or "用户"
    )
    lines = [f"您好，{recipient_name}：", ""]
    if action_url := payload.get("action_url"):
        lines.extend([subject, "", str(action_url)])
    else:
        lines.append(subject)
        for key, label in (
            ("applicant_name", "申请人姓名"),
            ("project_name", "项目"),
            ("resource_name", "算力资源"),
            ("gpu_count", "GPU 数量"),
            ("duration_days", "使用天数"),
            ("change_type", "变更类型"),
            ("amount", "变更数量"),
            ("expires_at", "到期时间"),
            ("comment", "审核意见"),
        ):
            value = payload.get(key)
            if value not in (None, ""):
                lines.append(f"{label}：{value}")
    lines.extend(["", "此邮件由 ComputeDock 自动发送。"])
    return subject, "\n".join(lines)


def send_notification(
    smtp_settings: SmtpConnectionSettings, notification: NotificationOutbox
) -> None:
    subject, body = render_notification(notification)
    send_email(
        smtp_settings,
        to_address=notification.to_address,
        cc_addresses=notification.cc_addresses,
        subject=subject,
        body=body,
    )


def process_one_notification(
    db: Session, settings: Settings, smtp_settings: SmtpConnectionSettings
) -> bool:
    now = utcnow()
    db.execute(
        update(NotificationOutbox)
        .where(
            NotificationOutbox.status == "sending",
            NotificationOutbox.updated_at < now - timedelta(minutes=15),
        )
        .values(status="pending", available_at=now, updated_at=now)
    )
    notification = db.scalar(
        select(NotificationOutbox)
        .where(
            NotificationOutbox.status.in_(("pending", "failed")),
            NotificationOutbox.available_at <= now,
            NotificationOutbox.attempts < settings.mail_max_attempts,
        )
        .order_by(NotificationOutbox.available_at, NotificationOutbox.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if notification is None:
        return False
    notification.status = "sending"
    notification.attempts += 1
    notification.updated_at = now
    db.commit()
    try:
        send_notification(smtp_settings, notification)
    except (OSError, RuntimeError, smtplib.SMTPException) as exc:
        notification.last_error = str(exc)[:2000]
        notification.status = (
            "failed" if notification.attempts >= settings.mail_max_attempts else "pending"
        )
        notification.available_at = utcnow() + timedelta(
            seconds=min(3600, 60 * (2 ** max(notification.attempts - 1, 0)))
        )
        notification.updated_at = utcnow()
        db.commit()
        return True
    notification.status = "sent"
    notification.sent_at = utcnow()
    notification.last_error = None
    notification.updated_at = notification.sent_at
    db.commit()
    return True


def schedule_expiry_notifications(db: Session) -> None:
    now = utcnow()
    requests = list(
        db.scalars(
            select(ComputeRequest).where(
                ComputeRequest.approval_status == "approved",
                ComputeRequest.expires_at.is_not(None),
                ComputeRequest.started_at.is_not(None),
            )
        )
    )
    admin_addresses = active_admin_emails(db)
    for request in requests:
        applicant = db.get(User, request.applicant_id)
        if applicant is None or not applicant.email or applicant.email_verified_at is None:
            continue
        expires_at = as_utc(request.expires_at)  # type: ignore[arg-type]
        if expires_at > now + timedelta(days=1):
            continue
        template = "compute_request_expired" if expires_at <= now else "compute_request_expiring"
        cc = [address for address in admin_addresses if address != applicant.email]
        enqueue_notification(
            db,
            idempotency_key=f"{template}:{request.id}:{expires_at.isoformat()}",
            template=template,
            to_address=applicant.email,
            cc_addresses=cc,
            payload={
                "full_name": applicant.full_name,
                "expires_at": expires_at.isoformat(),
            },
        )
    db.commit()


def auto_reject_expired_changes(db: Session) -> None:
    now = utcnow()
    changes = list(
        db.scalars(
            select(ComputeRequestChange)
            .join(ComputeRequest, ComputeRequest.id == ComputeRequestChange.request_id)
            .where(
                ComputeRequestChange.approval_status == "pending",
                ComputeRequest.expires_at.is_not(None),
                ComputeRequest.expires_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for change in changes:
        change.approval_status = "rejected"
        change.review_comment = "原申请已到期"
        change.reviewed_at = now
        change.updated_at = now
        record_audit(
            db,
            None,
            "compute_change.auto_rejected",
            "compute_request_change",
            change.id,
            before={"approval_status": "pending"},
            after={"approval_status": "rejected", "comment": change.review_comment},
        )
    db.commit()


def schedule_automatic_rejection_notifications(db: Session) -> None:
    requests = list(
        db.scalars(
            select(ComputeRequest).where(
                ComputeRequest.approval_status == "rejected",
                ComputeRequest.review_comment.in_(AUTO_REJECTION_REASONS),
            )
        )
    )
    for request in requests:
        applicant = db.get(User, request.applicant_id)
        if applicant and applicant.email and applicant.email_verified_at:
            enqueue_notification(
                db,
                idempotency_key=f"compute-request-reviewed:{request.id}",
                template="compute_request_rejected",
                to_address=applicant.email,
                payload={"full_name": applicant.full_name, "comment": request.review_comment or ""},
            )
    changes = list(
        db.scalars(
            select(ComputeRequestChange).where(
                ComputeRequestChange.approval_status == "rejected",
                ComputeRequestChange.review_comment.in_(AUTO_REJECTION_REASONS),
            )
        )
    )
    for change in changes:
        request = db.get(ComputeRequest, change.request_id)
        applicant = db.get(User, request.applicant_id) if request else None
        if applicant and applicant.email and applicant.email_verified_at:
            enqueue_notification(
                db,
                idempotency_key=f"compute-change-reviewed:{change.id}",
                template="compute_change_rejected",
                to_address=applicant.email,
                payload={"full_name": applicant.full_name, "comment": change.review_comment or ""},
            )
    db.commit()


ROLLUP_SQL = r"""
WITH observed AS (
    SELECT
        gs.resource_id,
        ci.compute_request_id,
        gs.container_id,
        gs.gpuid,
        gs.collected_at,
        gs.memory_used,
        gs.memory_total,
        gs.utilization,
        date_trunc('hour', gs.collected_at AT TIME ZONE :timezone)
            AT TIME ZONE :timezone AS bucket_start,
        lead(gs.collected_at) OVER (
            PARTITION BY gs.container_id, gs.gpuid ORDER BY gs.collected_at
        ) AS next_collected_at
    FROM gpu_samples gs
    JOIN container_instances ci ON ci.id = gs.container_id
    WHERE gs.collected_at >= :window_start
      AND gs.collected_at < :window_end
), weighted AS (
    SELECT
        observed.*,
        EXTRACT(EPOCH FROM GREATEST(
            interval '0 seconds',
            LEAST(
                COALESCE(next_collected_at, collected_at + make_interval(secs => :offline_seconds)),
                bucket_start + interval '1 hour',
                collected_at + make_interval(secs => :offline_seconds)
            ) - collected_at
        ))::double precision AS observed_seconds
    FROM observed
), aggregated AS (
    SELECT
        resource_id,
        compute_request_id,
        container_id,
        gpuid,
        bucket_start,
        COALESCE(
            SUM(utilization * observed_seconds) / NULLIF(SUM(observed_seconds), 0),
            AVG(utilization)
        )::double precision AS utilization_avg,
        MAX(utilization)::integer AS utilization_max,
        COALESCE(
            SUM(memory_used * observed_seconds) / NULLIF(SUM(observed_seconds), 0),
            AVG(memory_used)
        )::double precision AS memory_used_avg,
        MAX(memory_used)::bigint AS memory_used_max,
        MAX(memory_total)::bigint AS memory_total,
        SUM(observed_seconds)::integer AS online_seconds,
        COUNT(*)::integer AS sample_count,
        MIN(collected_at) AS first_collected_at,
        MAX(collected_at) AS last_collected_at
    FROM weighted
    GROUP BY resource_id, compute_request_id, container_id, gpuid, bucket_start
)
INSERT INTO hourly_gpu_rollups (
    resource_id, compute_request_id, container_id, gpuid, bucket_start,
    utilization_avg, utilization_max, memory_used_avg, memory_used_max,
    memory_total, online_seconds, sample_count, first_collected_at,
    last_collected_at, created_at, updated_at
)
SELECT
    resource_id, compute_request_id, container_id, gpuid, bucket_start,
    utilization_avg, utilization_max, memory_used_avg, memory_used_max,
    memory_total, online_seconds, sample_count, first_collected_at,
    last_collected_at, :now, :now
FROM aggregated
ON CONFLICT (container_id, gpuid, bucket_start) DO UPDATE SET
    resource_id = EXCLUDED.resource_id,
    compute_request_id = EXCLUDED.compute_request_id,
    utilization_avg = EXCLUDED.utilization_avg,
    utilization_max = EXCLUDED.utilization_max,
    memory_used_avg = EXCLUDED.memory_used_avg,
    memory_used_max = EXCLUDED.memory_used_max,
    memory_total = EXCLUDED.memory_total,
    online_seconds = EXCLUDED.online_seconds,
    sample_count = EXCLUDED.sample_count,
    first_collected_at = EXCLUDED.first_collected_at,
    last_collected_at = EXCLUDED.last_collected_at,
    updated_at = EXCLUDED.updated_at
"""


def day_window(target_day: date, timezone_name: str) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    start = datetime.combine(target_day, datetime_time.min, timezone).astimezone(UTC)
    end = datetime.combine(target_day + timedelta(days=1), datetime_time.min, timezone).astimezone(
        UTC
    )
    return start, end


def aggregate_day(db: Session, target_day: date, settings: Settings) -> None:
    start, end = day_window(target_day, settings.business_timezone)
    now = utcnow()
    db.execute(
        text(ROLLUP_SQL),
        {
            "window_start": start,
            "window_end": end,
            "timezone": settings.business_timezone,
            "offline_seconds": settings.offline_seconds,
            "now": now,
        },
    )


def aggregation_cutoff_day(settings: Settings, now: datetime | None = None) -> date:
    timezone = ZoneInfo(settings.business_timezone)
    local_now = as_utc(now or utcnow()).astimezone(timezone)
    days_back = 1 if local_now.hour >= WARNING_HOUR else 2
    return local_now.date() - timedelta(days=days_back)


def aggregate_pending_days(db: Session, settings: Settings) -> None:
    timezone = ZoneInfo(settings.business_timezone)
    cutoff = aggregation_cutoff_day(settings)
    checkpoint = db.get(WorkerCheckpoint, "hourly_rollups")
    if checkpoint is None:
        earliest = db.scalar(select(func.min(GpuSample.collected_at)))
        first_day = (
            as_utc(earliest).astimezone(timezone).date() if earliest else cutoff + timedelta(days=1)
        )
        checkpoint = WorkerCheckpoint(
            name="hourly_rollups",
            completed_through=first_day - timedelta(days=1),
            updated_at=utcnow(),
        )
        db.add(checkpoint)
        db.commit()
    target = (checkpoint.completed_through or cutoff) + timedelta(days=1)
    while target <= cutoff:
        aggregate_day(db, target, settings)
        checkpoint.completed_through = target
        checkpoint.updated_at = utcnow()
        db.commit()
        target += timedelta(days=1)


def effective_low_utilization_settings(db: Session) -> tuple[bool, int]:
    saved = db.get(SystemSetting, 1)
    if saved is None:
        return True, 10
    return saved.low_utilization_warning_enabled, saved.low_utilization_threshold


def summarize_pending_containers(
    db: Session,
    settings: Settings,
    batch_size: int = USAGE_SUMMARY_BATCH_SIZE,
) -> int:
    rollup_checkpoint = db.get(WorkerCheckpoint, "hourly_rollups")
    if rollup_checkpoint is None or rollup_checkpoint.completed_through is None:
        return 0
    timezone = ZoneInfo(settings.business_timezone)
    candidates = list(
        db.scalars(
            select(ContainerInstance)
            .where(
                ContainerInstance.usage_summary_status == "pending",
                ContainerInstance.removed_at.is_not(None),
            )
            .order_by(ContainerInstance.removed_at)
            .limit(batch_size)
        )
    )
    eligible = [
        container
        for container in candidates
        if as_utc(container.removed_at).astimezone(timezone).date()  # type: ignore[arg-type]
        <= rollup_checkpoint.completed_through
    ]
    if not eligible:
        return 0
    rollups = list(
        db.scalars(
            select(HourlyGpuRollup).where(
                HourlyGpuRollup.container_id.in_([container.id for container in eligible])
            )
        )
    )
    by_container: dict[object, list[HourlyGpuRollup]] = defaultdict(list)
    for rollup in rollups:
        by_container[rollup.container_id].append(rollup)
    completed_at = utcnow()
    for container in eligible:
        items = by_container[container.id]
        total_online_seconds = sum(max(item.online_seconds, 0) for item in items)
        memory_items = [item for item in items if item.memory_total > 0]
        memory_online_seconds = sum(max(item.online_seconds, 0) for item in memory_items)
        if total_online_seconds:
            gpu_average = (
                sum(item.utilization_avg * max(item.online_seconds, 0) for item in items)
                / total_online_seconds
            )
        else:
            gpu_average = None
        if memory_online_seconds:
            memory_average = (
                sum(
                    (item.memory_used_avg / item.memory_total) * max(item.online_seconds, 0)
                    for item in memory_items
                )
                / memory_online_seconds
                * 100
            )
        else:
            memory_average = None
        memory_max_values = [
            item.memory_used_max / item.memory_total * 100 for item in memory_items
        ]
        container.usage_duration_seconds = max(
            0,
            int(
                (
                    as_utc(container.removed_at)  # type: ignore[arg-type]
                    - as_utc(container.first_reported_at)
                ).total_seconds()
            ),
        )
        container.usage_gpu_count = len({item.gpuid for item in items})
        container.usage_gpu_utilization_avg = gpu_average
        container.usage_gpu_utilization_max = max(
            (item.utilization_max for item in items), default=None
        )
        container.usage_memory_utilization_avg = memory_average
        container.usage_memory_utilization_max = max(memory_max_values, default=None)
        container.usage_summary_status = "completed"
        container.usage_summary_completed_at = completed_at
    db.commit()
    return len(eligible)


def warning_target_day(settings: Settings, now: datetime | None = None) -> date | None:
    timezone = ZoneInfo(settings.business_timezone)
    local_now = as_utc(now or utcnow()).astimezone(timezone)
    if local_now.hour < WARNING_HOUR:
        return None
    return local_now.date() - timedelta(days=1)


def _format_business_time(value: datetime, settings: Settings) -> str:
    return (
        as_utc(value).astimezone(ZoneInfo(settings.business_timezone)).strftime("%Y-%m-%d %H:%M:%S")
    )


def enqueue_low_utilization_warnings(
    db: Session,
    target_day: date,
    settings: Settings,
    threshold: int,
) -> int:
    window_start, window_end = day_window(target_day, settings.business_timezone)
    observations = db.execute(
        select(
            GpuSample.container_id,
            func.min(GpuSample.collected_at),
            func.max(GpuSample.collected_at),
            func.count(func.distinct(GpuSample.gpuid)),
        )
        .join(ContainerInstance, ContainerInstance.id == GpuSample.container_id)
        .where(
            ContainerInstance.removed_at.is_(None),
            GpuSample.collected_at >= window_start,
            GpuSample.collected_at < window_end,
        )
        .group_by(GpuSample.container_id)
    ).all()
    observed: dict[object, tuple[datetime, datetime, int]] = {}
    for container_id, first_reported, last_reported, gpu_count in observations:
        if first_reported is None or last_reported is None:
            continue
        if as_utc(last_reported) - as_utc(first_reported) < MINIMUM_WARNING_SPAN:
            continue
        observed[container_id] = (first_reported, last_reported, int(gpu_count))
    if not observed:
        return 0
    rollups = list(
        db.scalars(
            select(HourlyGpuRollup).where(
                HourlyGpuRollup.container_id.in_(list(observed)),
                HourlyGpuRollup.bucket_start >= window_start,
                HourlyGpuRollup.bucket_start < window_end,
            )
        )
    )
    by_container: dict[object, list[HourlyGpuRollup]] = defaultdict(list)
    for rollup in rollups:
        by_container[rollup.container_id].append(rollup)
    containers = {
        container.id: container
        for container in db.scalars(
            select(ContainerInstance).where(
                ContainerInstance.id.in_(list(observed)),
                ContainerInstance.removed_at.is_(None),
            )
        )
    }
    low_metrics: list[tuple[ContainerInstance, dict[str, object]]] = []
    for container_id, observation in observed.items():
        container = containers.get(container_id)
        if container is None:
            continue
        items = by_container[container_id]
        online_seconds = sum(max(item.online_seconds, 0) for item in items)
        if online_seconds <= 0:
            continue
        usage_rate = (
            sum(item.utilization_avg * max(item.online_seconds, 0) for item in items)
            / online_seconds
        )
        if usage_rate >= threshold:
            continue
        first_reported, last_reported, gpu_count = observation
        low_metrics.append(
            (
                container,
                {
                    "container_id": str(container.id),
                    "name": container.name,
                    "usage_rate": usage_rate,
                    "gpu_count": gpu_count,
                    "first_reported_at": _format_business_time(first_reported, settings),
                    "last_reported_at": _format_business_time(last_reported, settings),
                },
            )
        )
    if not low_metrics:
        return 0
    by_request: dict[object, list[dict[str, object]]] = defaultdict(list)
    for container, metric in low_metrics:
        by_request[container.compute_request_id].append(metric)
    admin_addresses = active_admin_emails(db)
    enqueued = 0
    now = utcnow()
    for request_id, metrics in by_request.items():
        metrics.sort(key=lambda item: str(item["name"]))
        request = db.get(ComputeRequest, request_id)
        if request is None:
            continue
        applicant = db.get(User, request.applicant_id)
        project = db.get(Project, request.project_id)
        resource = db.get(ComputeResource, request.resource_id)
        if applicant is None or not applicant.email or project is None or resource is None:
            continue
        enqueue_notification(
            db,
            idempotency_key=f"low-utilization:request:{request.id}:{target_day.isoformat()}",
            template="low_utilization_warning",
            to_address=applicant.email,
            cc_addresses=[address for address in admin_addresses if address != applicant.email],
            payload={
                "full_name": applicant.full_name,
                "applicant_name": applicant.full_name,
                "project_name": project.name,
                "resource_name": resource.name,
                "approved_gpu_count": request.gpu_count,
                "statistics_date": target_day.isoformat(),
                "threshold": threshold,
                "request_expired": bool(request.expires_at and as_utc(request.expires_at) <= now),
                "containers": metrics,
            },
        )
        enqueued += 1
    db.commit()
    return enqueued


def schedule_low_utilization_warnings(db: Session, settings: Settings) -> int:
    target_day = warning_target_day(settings)
    if target_day is None:
        return 0
    checkpoint = db.get(WorkerCheckpoint, "low_utilization_warnings")
    if (
        checkpoint is not None
        and checkpoint.completed_through is not None
        and checkpoint.completed_through >= target_day
    ):
        return 0
    rollup_checkpoint = db.get(WorkerCheckpoint, "hourly_rollups")
    if rollup_checkpoint is None or rollup_checkpoint.completed_through is None:
        return 0
    if rollup_checkpoint.completed_through < target_day:
        return 0
    enabled, threshold = effective_low_utilization_settings(db)
    enqueued = (
        enqueue_low_utilization_warnings(db, target_day, settings, threshold) if enabled else 0
    )
    if checkpoint is None:
        checkpoint = WorkerCheckpoint(
            name="low_utilization_warnings",
            completed_through=target_day,
            updated_at=utcnow(),
        )
        db.add(checkpoint)
    else:
        checkpoint.completed_through = target_day
        checkpoint.updated_at = utcnow()
    db.commit()
    return enqueued


def run_once(settings: Settings | None = None) -> None:
    current_settings = settings or get_settings()
    with SessionLocal() as db:
        aggregate_pending_days(db, current_settings)
        summarize_pending_containers(db, current_settings)
        schedule_low_utilization_warnings(db, current_settings)
        auto_reject_expired_changes(db)
        schedule_automatic_rejection_notifications(db)
        schedule_expiry_notifications(db)
        smtp_settings = effective_smtp_settings(db, current_settings)
        while process_one_notification(db, current_settings, smtp_settings):
            pass


def main() -> None:
    parser = argparse.ArgumentParser(prog="computedock-monitor-worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.once:
        run_once(settings)
        return
    while True:
        run_once(settings)
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()

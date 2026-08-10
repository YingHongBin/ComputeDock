from __future__ import annotations

import smtplib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auditing import record_audit
from ..auth import AuthContext, require_admin, require_admin_csrf
from ..config import Settings, get_settings
from ..database import get_db
from ..models import SmtpSetting, SystemSetting
from ..notifications import effective_api_base_url
from ..schemas import (
    GeneralSettingsInput,
    GeneralSettingsView,
    SmtpSettingsInput,
    SmtpSettingsView,
)
from ..security import utcnow
from ..smtp import (
    SmtpConnectionSettings,
    database_smtp_settings,
    effective_smtp_settings,
    send_email,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def settings_view(db: Session, settings: Settings) -> SmtpSettingsView:
    saved = db.get(SmtpSetting, 1)
    effective = (
        database_smtp_settings(saved)
        if saved is not None
        else effective_smtp_settings(db, settings)
    )
    return SmtpSettingsView(
        host=effective.host,
        port=effective.port,
        username=effective.username,
        from_email=effective.from_email,
        from_name=effective.from_name,
        use_tls=effective.use_tls,
        password_set=bool(effective.password),
        source="database" if saved is not None else "environment",
    )


def connection_from_payload(
    db: Session, payload: SmtpSettingsInput, settings: Settings
) -> SmtpConnectionSettings:
    current = effective_smtp_settings(db, settings)
    return SmtpConnectionSettings(
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=current.password if payload.password is None else payload.password,
        from_email=payload.from_email,
        from_name=payload.from_name,
        use_tls=payload.use_tls,
        implicit_tls=payload.use_tls and payload.port == 465,
    )


@router.get("/smtp", response_model=SmtpSettingsView)
def get_smtp_settings(
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SmtpSettingsView:
    return settings_view(db, settings)


@router.put("/smtp", response_model=SmtpSettingsView)
def update_smtp_settings(
    payload: SmtpSettingsInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SmtpSettingsView:
    connection = connection_from_payload(db, payload, settings)
    saved = db.get(SmtpSetting, 1)
    before = None
    if saved is None:
        saved = SmtpSetting(id=1, updated_by_id=auth.user.id, updated_at=utcnow())
        db.add(saved)
    else:
        before = {
            "host": saved.host,
            "port": saved.port,
            "username": saved.username,
            "from_email": saved.from_email,
            "from_name": saved.from_name,
            "use_tls": saved.use_tls,
            "password_set": bool(saved.password),
        }
    saved.host = connection.host
    saved.port = connection.port
    saved.username = connection.username
    saved.password = connection.password
    saved.from_email = connection.from_email
    saved.from_name = connection.from_name
    saved.use_tls = connection.use_tls
    saved.updated_by_id = auth.user.id
    saved.updated_at = utcnow()
    record_audit(
        db,
        auth.user,
        "settings.smtp.update",
        "smtp_settings",
        "1",
        before=before,
        after={
            "host": saved.host,
            "port": saved.port,
            "username": saved.username,
            "from_email": saved.from_email,
            "from_name": saved.from_name,
            "use_tls": saved.use_tls,
            "password_set": bool(saved.password),
            "password_changed": payload.password is not None,
        },
    )
    db.commit()
    return settings_view(db, settings)


@router.post("/smtp/test", status_code=status.HTTP_200_OK)
def send_test_email(
    payload: SmtpSettingsInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if not auth.user.email:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "当前管理员需要先绑定邮箱",
        )
    connection = connection_from_payload(db, payload, settings)
    try:
        send_email(
            connection,
            to_address=auth.user.email,
            subject="ComputeDock SMTP 测试邮件",
            body="这是一封 ComputeDock SMTP 配置测试邮件。收到此邮件表示配置可用。",
        )
    except (OSError, RuntimeError, smtplib.SMTPException) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)[:1000]) from exc
    record_audit(
        db,
        auth.user,
        "settings.smtp.test",
        "smtp_settings",
        "1",
        after={"recipient": auth.user.email},
    )
    db.commit()
    return {"status": "sent", "recipient": auth.user.email}


@router.get("/general", response_model=GeneralSettingsView)
def get_general_settings(
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GeneralSettingsView:
    saved = db.get(SystemSetting, 1)
    return GeneralSettingsView(
        api_base_url=effective_api_base_url(db, settings),
        source="database" if saved is not None else "environment",
    )


@router.put("/general", response_model=GeneralSettingsView)
def update_general_settings(
    payload: GeneralSettingsInput,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> GeneralSettingsView:
    saved = db.get(SystemSetting, 1)
    before = None
    if saved is None:
        saved = SystemSetting(id=1, updated_by_id=auth.user.id, updated_at=utcnow())
        db.add(saved)
    else:
        before = {"api_base_url": saved.api_base_url}
    saved.api_base_url = payload.api_base_url
    saved.updated_by_id = auth.user.id
    saved.updated_at = utcnow()
    record_audit(
        db,
        auth.user,
        "settings.general.update",
        "system_settings",
        "1",
        before=before,
        after={"api_base_url": saved.api_base_url},
    )
    db.commit()
    return GeneralSettingsView(api_base_url=saved.api_base_url, source="database")

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy.orm import Session

from .config import Settings
from .models import SmtpSetting


@dataclass(frozen=True)
class SmtpConnectionSettings:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    use_tls: bool
    implicit_tls: bool = False


def environment_smtp_settings(settings: Settings) -> SmtpConnectionSettings:
    return SmtpConnectionSettings(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_email=settings.smtp_from_address,
        from_name=settings.smtp_from_name,
        use_tls=settings.smtp_starttls or settings.smtp_ssl,
        implicit_tls=settings.smtp_ssl,
    )


def database_smtp_settings(setting: SmtpSetting) -> SmtpConnectionSettings:
    return SmtpConnectionSettings(
        host=setting.host,
        port=setting.port,
        username=setting.username,
        password=setting.password,
        from_email=setting.from_email,
        from_name=setting.from_name,
        use_tls=setting.use_tls,
        implicit_tls=setting.use_tls and setting.port == 465,
    )


def effective_smtp_settings(db: Session, settings: Settings) -> SmtpConnectionSettings:
    saved = db.get(SmtpSetting, 1)
    if saved is not None:
        return database_smtp_settings(saved)
    return environment_smtp_settings(settings)


def send_email(
    settings: SmtpConnectionSettings,
    *,
    to_address: str,
    subject: str,
    body: str,
    cc_addresses: list[str] | None = None,
) -> None:
    if not settings.host or not settings.from_email:
        raise RuntimeError("必须配置 SMTP Host 和 From Email")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((settings.from_name, settings.from_email))
    message["To"] = to_address
    if cc_addresses:
        message["Cc"] = ", ".join(cc_addresses)
    message.set_content(body)
    smtp_class = smtplib.SMTP_SSL if settings.implicit_tls else smtplib.SMTP
    with smtp_class(settings.host, settings.port, timeout=15) as smtp:
        if settings.use_tls and not settings.implicit_tls:
            smtp.starttls()
        if settings.username:
            smtp.login(settings.username, settings.password)
        smtp.send_message(message)

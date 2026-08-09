from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str


class Settings(DatabaseSettings):
    admin_username: str
    admin_password: str
    admin_email: str | None = None
    public_base_url: str = "http://127.0.0.1:8000"
    business_timezone: str = "Asia/Shanghai"
    cookie_secure: bool = True
    allowed_origins: str = ""
    frontend_dir: Path = Path("/opt/computedock-monitor/frontend")
    session_hours: int = 12
    offline_seconds: int = 120
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    worker_poll_seconds: int = 60
    mail_max_attempts: int = 5

    @property
    def allowed_origin_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()  # type: ignore[call-arg]

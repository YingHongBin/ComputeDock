from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

password_hasher = PasswordHasher()


def utcnow() -> datetime:
    return datetime.now(UTC)


def digest_secret(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def make_resource_token() -> str:
    return f"cdr_{secrets.token_urlsafe(32)}"


@dataclass(frozen=True)
class SessionSecrets:
    token: str
    csrf_token: str
    token_hash: bytes
    csrf_hash: bytes
    expires_at: datetime


def make_session(hours: int) -> SessionSecrets:
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    return SessionSecrets(
        token=token,
        csrf_token=csrf_token,
        token_hash=digest_secret(token),
        csrf_hash=digest_secret(csrf_token),
        expires_at=utcnow() + timedelta(hours=hours),
    )

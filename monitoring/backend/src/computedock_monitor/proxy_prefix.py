from __future__ import annotations

import re
from html import escape

from fastapi import Request

FORWARDED_PREFIX_HEADER = "X-Forwarded-Prefix"
_PREFIX_PATTERN = re.compile(r"^/[A-Za-z0-9._~/-]+/?$")


def normalize_forwarded_prefix(value: str | None) -> str:
    if value is None or not value.strip() or value.strip() == "/":
        return ""

    prefix = value.strip()
    if (
        not _PREFIX_PATTERN.fullmatch(prefix)
        or "//" in prefix
        or "%" in prefix
        or any(segment in {".", ".."} for segment in prefix.split("/"))
    ):
        raise ValueError("invalid X-Forwarded-Prefix")
    return prefix.rstrip("/")


def request_prefix(request: Request) -> str:
    stored = getattr(request.state, "forwarded_prefix", None)
    if stored is not None:
        return stored
    return normalize_forwarded_prefix(request.headers.get(FORWARDED_PREFIX_HEADER))


def prefix_path(prefix: str) -> str:
    return f"{prefix}/" if prefix else "/"


def inject_base_href(index_html: str, prefix: str) -> str:
    marker = "<head>"
    if marker not in index_html:
        raise ValueError("frontend index.html has no <head> element")
    base = escape(prefix_path(prefix), quote=True)
    return index_html.replace(marker, f'{marker}\n    <base href="{base}" />', 1)

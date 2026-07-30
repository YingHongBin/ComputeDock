import pytest

from computedock_monitor.proxy_prefix import (
    inject_base_href,
    normalize_forwarded_prefix,
    prefix_path,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("/", ""),
        ("/console", "/console"),
        ("/platform/tools/console/", "/platform/tools/console"),
    ],
)
def test_normalize_forwarded_prefix(value: str | None, expected: str) -> None:
    assert normalize_forwarded_prefix(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "console",
        "//console",
        "/console//admin",
        "/console/../admin",
        "/console?next=/admin",
        "/console%2Fadmin",
        "https://example.com/console",
    ],
)
def test_reject_invalid_forwarded_prefix(value: str) -> None:
    with pytest.raises(ValueError, match="invalid X-Forwarded-Prefix"):
        normalize_forwarded_prefix(value)


def test_inject_base_href_and_cookie_path() -> None:
    prefix = normalize_forwarded_prefix("/platform/console/")
    html = inject_base_href("<!doctype html><html><head></head></html>", prefix)
    assert '<base href="/platform/console/" />' in html
    assert prefix_path(prefix) == "/platform/console/"
    assert prefix_path("") == "/"

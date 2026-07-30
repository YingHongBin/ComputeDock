from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


IDENTITY_FILENAME = "identity.json"


class IdentityError(RuntimeError):
    """Raised when the persistent container identity cannot be used safely."""


def _read_identity(path: Path) -> str:
    try:
        document: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityError(f"cannot read identity file {path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(
        document.get("container_name"), str
    ):
        raise IdentityError(
            f"identity file {path} must contain a string container_name"
        )
    return document["container_name"]


def _write_new_identity(path: Path, container_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"container_name": container_name}, ensure_ascii=False, separators=(",", ":")
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            return
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise IdentityError(f"cannot create identity file {path}: {exc}") from exc
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def load_or_create_identity(state_dir: Path, configured_name: str | None) -> str:
    path = state_dir / IDENTITY_FILENAME
    if path.exists():
        stored_name = _read_identity(path)
        if configured_name is not None and configured_name != stored_name:
            raise IdentityError(
                "configured container name does not match the persistent identity"
            )
        return stored_name

    if configured_name is None:
        raise IdentityError(
            "container name is required when no persistent identity exists"
        )

    _write_new_identity(path, configured_name)
    stored_name = _read_identity(path)
    if stored_name != configured_name:
        raise IdentityError(
            "another process created a different persistent container identity"
        )
    return stored_name

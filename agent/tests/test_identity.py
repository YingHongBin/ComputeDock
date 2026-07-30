from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from computedock_agent.identity import IdentityError, load_or_create_identity


class IdentityTests(unittest.TestCase):
    def test_first_name_is_persisted_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            self.assertEqual(load_or_create_identity(state_dir, "容器 one"), "容器 one")
            self.assertEqual(load_or_create_identity(state_dir, None), "容器 one")
            document = json.loads(
                (state_dir / "identity.json").read_text(encoding="utf-8")
            )
            self.assertEqual(document, {"container_name": "容器 one"})
            self.assertEqual((state_dir / "identity.json").stat().st_mode & 0o777, 0o600)

    def test_container_name_is_not_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_or_create_identity(Path(directory), ""), "")

    def test_different_persisted_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            load_or_create_identity(state_dir, "first")
            with self.assertRaises(IdentityError):
                load_or_create_identity(state_dir, "second")

    def test_name_is_required_only_on_first_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(IdentityError):
                load_or_create_identity(Path(directory), None)

    def test_corrupt_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(IdentityError):
                load_or_create_identity(Path(directory), None)


if __name__ == "__main__":
    unittest.main()

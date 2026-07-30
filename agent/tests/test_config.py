from __future__ import annotations

import unittest
from pathlib import Path

from computedock_agent.config import (
    ConfigurationError,
    build_parser,
    resolve_config,
)


class ConfigTests(unittest.TestCase):
    def parse(self, *arguments: str, environment: dict[str, str] | None = None):
        namespace = build_parser().parse_args(["run", *arguments])
        resolved_environment = {"COMPUTEDOCK_STATE_DIR": "/tmp/test-state"}
        if environment is not None:
            resolved_environment.update(environment)
        return resolve_config(namespace, resolved_environment)

    def test_command_line_values_override_environment(self) -> None:
        config = self.parse(
            "--server-url",
            "http://cli.invalid/full/path",
            "--container-name",
            "cli name",
            "--interval",
            "15",
            "--token",
            "cli-token",
            environment={
                "COMPUTEDOCK_SERVER_URL": "http://env.invalid",
                "COMPUTEDOCK_CONTAINER_NAME": "env name",
                "COMPUTEDOCK_INTERVAL": "30",
                "COMPUTEDOCK_TOKEN": "env-token",
            },
        )
        self.assertEqual(config.server_url, "http://cli.invalid/full/path")
        self.assertEqual(config.configured_container_name, "cli name")
        self.assertEqual(config.interval, 15)
        self.assertEqual(config.token, "cli-token")

    def test_environment_only_configuration(self) -> None:
        config = self.parse(
            environment={
                "COMPUTEDOCK_SERVER_URL": "not-validated",
                "COMPUTEDOCK_CONTAINER_NAME": "",
                "COMPUTEDOCK_INTERVAL": "5",
                "COMPUTEDOCK_TOKEN": "token",
                "COMPUTEDOCK_STATE_DIR": "/tmp/custom-state",
            }
        )
        self.assertEqual(config.server_url, "not-validated")
        self.assertEqual(config.configured_container_name, "")
        self.assertEqual(config.state_dir, Path("/tmp/custom-state"))

    def test_test_output_does_not_require_url_or_token(self) -> None:
        config = self.parse(
            "--container-name",
            "worker",
            "--interval",
            "10",
            "--test-output",
            "/tmp/metrics.jsonl",
        )
        self.assertIsNone(config.server_url)
        self.assertIsNone(config.token)
        self.assertEqual(config.test_output, Path("/tmp/metrics.jsonl"))

    def test_state_directory_must_be_provided_by_the_caller(self) -> None:
        namespace = build_parser().parse_args(
            ["run", "--interval", "10", "--server-url", "url", "--token", "token"]
        )
        with self.assertRaisesRegex(
            ConfigurationError, "COMPUTEDOCK_STATE_DIR must be provided"
        ):
            resolve_config(namespace, {})

    def test_normal_mode_requires_url_and_token(self) -> None:
        with self.assertRaises(ConfigurationError):
            self.parse("--interval", "15", "--token", "token")
        with self.assertRaises(ConfigurationError):
            self.parse("--interval", "15", "--server-url", "url")

    def test_interval_must_be_an_integer_in_range(self) -> None:
        base = ["--server-url", "url", "--token", "token"]
        for invalid in ("4", "3601", "1.5", "invalid"):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigurationError):
                self.parse(*base, "--interval", invalid)


if __name__ == "__main__":
    unittest.main()

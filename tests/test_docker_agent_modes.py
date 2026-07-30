from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DockerAgentModeTests(unittest.TestCase):
    def build_docker_arguments(self, mode: str) -> list[str]:
        command = rf'''
            source create_container.sh
            GPU_SELECTION=""
            CPU_SELECTION="0-1"
            MEMORY_GIB="8"
            SHM_MIB="4096"
            SSH_PORT="52236"
            USERNAME_VALUE="worker"
            CONTAINER_NAME="worker-01"
            AGENT_INTERVAL="15"
            AGENT_MODE="{mode}"
            AGENT_SERVER_URL="https://example.invalid/full/path"
            MOUNT_PATH="/data/worker"
            IMAGE_VALUE="computedock:test"
            build_docker_command
            printf '%s\n' "${{DOCKER_COMMAND[@]}}"
        '''
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.splitlines()

    def test_report_mode_passes_url_and_token_without_test_output(self) -> None:
        arguments = self.build_docker_arguments("report")
        self.assertIn(
            "COMPUTEDOCK_SERVER_URL=https://example.invalid/full/path", arguments
        )
        self.assertIn("COMPUTEDOCK_TOKEN", arguments)
        self.assertFalse(
            any(argument.startswith("COMPUTEDOCK_TEST_OUTPUT=") for argument in arguments)
        )

    def test_test_mode_passes_output_without_url_or_token(self) -> None:
        arguments = self.build_docker_arguments("test")
        self.assertIn("COMPUTEDOCK_TEST_OUTPUT=1", arguments)
        self.assertNotIn("COMPUTEDOCK_TOKEN", arguments)
        self.assertFalse(
            any(argument.startswith("COMPUTEDOCK_SERVER_URL=") for argument in arguments)
        )

    def test_container_entrypoint_accepts_test_mode_without_remote_config(self) -> None:
        entrypoint = (PROJECT_ROOT / "init_container.sh").read_text(encoding="utf-8")
        self.assertIn('if [[ -z "${COMPUTEDOCK_TEST_OUTPUT:-}" ]]', entrypoint)
        self.assertIn("require_environment_variable COMPUTEDOCK_SERVER_URL", entrypoint)
        self.assertIn("require_environment_variable COMPUTEDOCK_TOKEN", entrypoint)

    def test_image_prepares_the_fixed_test_output_directory(self) -> None:
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("/opt/computedock-agent/test-samples.jsonl", dockerfile)
        self.assertIn("-o computedock-agent", dockerfile)
        self.assertIn("-g computedock-agent", dockerfile)

    def test_service_script_passes_the_fixed_test_output_path(self) -> None:
        service_script = (PROJECT_ROOT / "run_agent_service.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'TEST_OUTPUT_PATH="/opt/computedock-agent/test-samples.jsonl"',
            service_script,
        )
        self.assertIn('agent_arguments+=(--test-output "$TEST_OUTPUT_PATH")', service_script)

    def test_command_preview_displays_plaintext_password_and_token(self) -> None:
        command = r'''
            source create_container.sh
            password="plain-password"
            agent_token="plain-token"
            AGENT_MODE="report"
            DOCKER_COMMAND=(docker run example:image)
            print_command_preview
        '''
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("NEW_PWD=plain-password", result.stdout)
        self.assertIn("COMPUTEDOCK_TOKEN=plain-token", result.stdout)
        self.assertNotIn("******", result.stdout)

    def test_shell_scripts_pass_syntax_check(self) -> None:
        scripts = [
            PROJECT_ROOT / "create_container.sh",
            PROJECT_ROOT / "init_container.sh",
            PROJECT_ROOT / "run_agent_service.sh",
            PROJECT_ROOT / "healthcheck.sh",
        ]
        subprocess.run(
            ["bash", "-n", *(str(script) for script in scripts)],
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()

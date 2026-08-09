from __future__ import annotations

import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DockerAgentModeTests(unittest.TestCase):
    def test_creation_script_uses_production_agent_url_by_default(self) -> None:
        command = r'''
            source create_container.sh
            printf '%s\n' "$AGENT_SERVER_URL"
        '''
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout.strip(),
            "https://nbdataxai.com/monitor/api/v1/agent/samples",
        )

    def test_creation_script_loads_defaults_from_config(self) -> None:
        command = r'''
            source create_container.sh
            load_configuration
            printf '%s\n' "$IMAGE_DEFAULT" "$DATA_ROOT_DEFAULT"
        '''
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout.splitlines(),
            ["dilab-base:cuda-12.8-v5", "/data"],
        )

    def test_environment_can_override_config_defaults(self) -> None:
        command = r'''
            source create_container.sh
            COMPUTEDOCK_DEFAULT_IMAGE="computedock:override"
            COMPUTEDOCK_DATA_ROOT="/srv/override/"
            load_configuration
            printf '%s\n' "$IMAGE_DEFAULT" "$DATA_ROOT_DEFAULT"
        '''
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout.splitlines(),
            ["computedock:override", "/srv/override"],
        )

    def test_default_config_is_resolved_from_execution_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            execution_directory = Path(directory)
            (execution_directory / "create_container.conf").write_text(
                "IMAGE_DEFAULT=computedock:from-cwd\n"
                "DATA_ROOT_DEFAULT=/srv/from-cwd\n",
                encoding="utf-8",
            )
            script = shlex.quote(str(PROJECT_ROOT / "create_container.sh"))
            command = f'''
                source {script}
                load_configuration
                printf '%s\n' "$IMAGE_DEFAULT" "$DATA_ROOT_DEFAULT"
            '''
            result = subprocess.run(
                ["bash", "-c", command],
                cwd=execution_directory,
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertEqual(
            result.stdout.splitlines(),
            ["computedock:from-cwd", "/srv/from-cwd"],
        )

    def test_missing_config_in_execution_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = shlex.quote(str(PROJECT_ROOT / "create_container.sh"))
            command = f'''\
                source {script}
                load_configuration
            '''
            result = subprocess.run(
                ["bash", "-c", command],
                cwd=directory,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("当前执行目录缺少配置文件", result.stderr)

    def test_mount_path_uses_data_root_and_container_name(self) -> None:
        command = r'''
            source create_container.sh
            CONTAINER_NAME="worker-01"
            prompt_data_root <<< "/srv/compute/"
            printf '\n%s\n%s\n' "$DATA_ROOT" "$MOUNT_PATH"
        '''
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout.splitlines()[-2:],
            ["/srv/compute", "/srv/compute/worker-01"],
        )

    def test_mount_path_is_created_and_owned_by_1001(self) -> None:
        command = r'''
            source create_container.sh
            MOUNT_PATH="/data/worker-01"
            run_as_root() {
                printf '%s\n' "$*"
            }
            prepare_mount_path
        '''
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "mkdir -p -- /data/worker-01",
                "chown 1001:1001 -- /data/worker-01",
            ],
        )

    def test_mount_owner_matches_the_container_user_contract(self) -> None:
        creation_script = (PROJECT_ROOT / "create_container.sh").read_text(
            encoding="utf-8"
        )
        entrypoint = (PROJECT_ROOT / "init_container.sh").read_text(encoding="utf-8")

        for content in (creation_script, entrypoint):
            self.assertIn('readonly DEFAULT_UID="1001"', content)
            self.assertIn('readonly DEFAULT_GID="1001"', content)
        self.assertIn('interactive_uid=$(id -u "$NEW_USER")', entrypoint)
        self.assertIn('interactive_gid=$(id -g "$NEW_USER")', entrypoint)
        self.assertIn(
            "must use UID:GID ${DEFAULT_UID}:${DEFAULT_GID}", entrypoint
        )

    def test_sudo_authentication_precedes_mount_preparation(self) -> None:
        creation_script = (PROJECT_ROOT / "create_container.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("sudo -v", creation_script)
        confirmation = creation_script.index(
            'confirm "确认创建并启动容器吗？"'
        )
        authentication = creation_script.index("request_root_access", confirmation)
        preparation = creation_script.index("prepare_mount_path", authentication)
        self.assertLess(confirmation, authentication)
        self.assertLess(authentication, preparation)

    def build_docker_arguments(
        self, mode: str, gpu_selection: str = ""
    ) -> list[str]:
        command = rf'''
            source create_container.sh
            GPU_SELECTION="{gpu_selection}"
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

    def test_no_gpu_mode_explicitly_disables_nvidia_device_injection(self) -> None:
        arguments = self.build_docker_arguments("report")
        self.assertIn("NVIDIA_VISIBLE_DEVICES=void", arguments)
        self.assertNotIn("--gpus", arguments)

    def test_gpu_mode_requests_only_selected_devices(self) -> None:
        arguments = self.build_docker_arguments("report", "1,3")
        self.assertNotIn("NVIDIA_VISIBLE_DEVICES=void", arguments)
        gpu_option = arguments.index("--gpus")
        self.assertEqual(arguments[gpu_option + 1], '"device=1,3"')

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

    def test_legacy_container_installer_configures_supervisor_restart(self) -> None:
        installer = (PROJECT_ROOT / "agent" / "install_agent_service.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'DEFAULT_SERVER_URL="https://nbdataxai.com/monitor/api/v1/agent/samples"',
            installer,
        )
        self.assertIn("autorestart=unexpected", installer)
        self.assertIn("exitcodes=0,2", installer)
        self.assertIn("supervisord -c /etc/supervisor/supervisord.conf", installer)
        self.assertIn("必须在目标算力容器内以 root 用户执行", installer)
        self.assertNotIn("docker exec", installer)
        self.assertNotIn("docker cp", installer)

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
            PROJECT_ROOT / "agent" / "install_agent_service.sh",
        ]
        subprocess.run(
            ["bash", "-n", *(str(script) for script in scripts)],
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()

"""Exercise the interactive allocation logic without a Docker daemon or remote writes."""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ContainerAllocationTests(unittest.TestCase):
    def run_script(self, script, input_text=""):
        return subprocess.run(
            ["bash", "-c", "source create_container.sh\n" + script],
            cwd=ROOT,
            input=input_text,
            text=True,
            capture_output=True,
        )

    def test_zero_gpu_approval_uses_only_cpu_and_memory(self):
        result = self.run_script(r"""
            APPROVED_GPU_COUNT=0; APPROVED_CPU_CORES=2; APPROVED_MEMORY_GIB=8
            ONLINE_CPU_SPEC=0-3; ONLINE_CPU_CSV=0,1,2,3
            GPU_DATA=""; HOST_MEM_TOTAL_KIB=67108864
            docker() { if [[ "$1" == ps ]]; then return 0; else return 1; fi; }
            confirm() { return 0; }
            configure_approved_resources
            validate_approved_selection || exit 1
            printf 'RESULT=%s|%s|%s\n' "$GPU_SELECTION" "$CPU_SELECTION" "$MEMORY_GIB"
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESULT=|0-1|8", result.stdout)

    def test_service_root_and_full_endpoint_preserve_proxy_prefix(self):
        for url in (
            "https://example.test/monitor",
            "https://example.test/monitor/",
            "https://example.test/monitor/api/v1/agent/samples",
        ):
            result = self.run_script(
                f'AGENT_SERVER_URL={url}; normalize_agent_url; printf "%s\\n" "$ALLOCATION_URL"'
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                "https://example.test/monitor/api/v1/agent/allocation",
            )
        result = self.run_script(
            'AGENT_SERVER_URL="https://user:pass@example.test"; normalize_agent_url'
        )
        self.assertNotEqual(result.returncode, 0)

    def test_lookup_validates_response_and_sends_token_only_in_header(self):
        result = self.run_script(r"""
            agent_token=cda_secret
            ALLOCATION_URL=https://example.test/api/v1/agent/allocation
            curl() {
                case "$*" in *cda_secret*) return 1;; esac
                IFS= read -r header
                [[ "$header" == 'header = "Authorization: Bearer cda_secret"' ]] || return 1
                printf '%s\n200' '{"request_id":"12345678-1234-1234-1234-123456789012","resource_name":"server","gpu_model":"A100","gpu_count":0,"cpu_cores":8,"memory_gib":32}'
            }
            fetch_approved_allocation
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "12345678-1234-1234-1234-123456789012 0 8 32"
        )
        self.assertNotIn("cda_secret", result.stdout + result.stderr)

    def test_lookup_stops_on_http_error_or_invalid_capacity(self):
        for response in (
            '{"detail":"expired"}\\n409',
            '{"request_id":"12345678-1234-1234-1234-123456789012","gpu_count":1,"cpu_cores":0,"memory_gib":32}\\n200',
        ):
            result = self.run_script(f"""
                agent_token=cda_test
                ALLOCATION_URL=https://example.test/api/v1/agent/allocation
                curl() {{ cat >/dev/null; printf '{response}'; }}
                fetch_approved_allocation
            """)
            self.assertNotEqual(result.returncode, 0)

    def test_auto_selection_avoids_running_bindings_and_uses_approved_memory(self):
        result = self.run_script(r"""
            APPROVED_GPU_COUNT=1
            APPROVED_CPU_CORES=2
            APPROVED_MEMORY_GIB=8
            ONLINE_CPU_SPEC=0-5
            GPU_DATA=$'0, GPU-0, A100, 100\n1, GPU-1, A100, 100'
            HOST_MEM_TOTAL_KIB=67108864
            docker() {
                if [[ "$1" == ps ]]; then printf 'running\n'; return; fi
                case "$3" in
                    '{{.HostConfig.CpusetCpus}}') printf '0-1,4\n';;
                    '{{.HostConfig.Memory}}') printf '1073741824\n';;
                    *) return 1;;
                esac
            }
            container_gpu_binding() { printf '0\n'; }
            confirm() { return 0; }
            configure_approved_resources
            printf 'RESULT=%s|%s|%s|%s\n' "$GPU_SELECTION" "$CPU_SELECTION" "$MEMORY_GIB" "$SHM_MIB"
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESULT=1|2-3|8|4096", result.stdout)

    def test_unrestricted_or_unknown_bindings_are_not_auto_selected(self):
        result = self.run_script(r"""
            ONLINE_CPU_SPEC=0-3
            ONLINE_CPU_CSV=0,1,2,3
            GPU_DATA=$'0, GPU-0, A100, 100\n1, GPU-1, A100, 100'
            docker() {
                if [[ "$1" == ps ]]; then printf 'running\n'; return; fi
                case "$3" in
                    '{{.HostConfig.CpusetCpus}}') printf '\n';;
                    '{{.HostConfig.Memory}}') printf '0\n';;
                esac
            }
            container_gpu_binding() { printf 'all\n'; }
            find_free_resources
            printf '%s|%s|%s\n' "$FREE_GPU_CSV" "$FREE_CPU_CSV" "$MEMORY_ALLOCATION_UNKNOWN"
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "||1")

    def test_shortage_allows_manual_shared_bindings_without_changing_counts(self):
        result = self.run_script(
            r"""
            APPROVED_GPU_COUNT=2
            APPROVED_CPU_CORES=2
            APPROVED_MEMORY_GIB=8
            ONLINE_CPU_SPEC=0-3
            ONLINE_CPU_CSV=0,1,2,3
            GPU_DATA=$'0, GPU-0, A100, 100\n1, GPU-1, A100, 100'
            HOST_MEM_TOTAL_KIB=67108864
            find_free_resources() {
                FREE_GPU_CSV=0; FREE_CPU_CSV=0
                RUNNING_MEMORY_BYTES=0; MEMORY_ALLOCATION_UNKNOWN=0
            }
            confirm() { return 0; }
            configure_approved_resources
            printf 'RESULT=%s|%s|%s\n' "$GPU_SELECTION" "$CPU_SELECTION" "$MEMORY_GIB"
        """,
            "0\n0,1\n0\n0-1\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESULT=0,1|0-1|8", result.stdout)
        self.assertIn("必须选择获批的 2 张 GPU", result.stderr)
        self.assertIn("必须选择获批的 2 个 CPU 核", result.stderr)

    def test_shortage_can_be_cancelled(self):
        result = self.run_script(r"""
            APPROVED_GPU_COUNT=2; APPROVED_CPU_CORES=8; APPROVED_MEMORY_GIB=32
            find_free_resources() { FREE_GPU_CSV=""; FREE_CPU_CSV=""; }
            confirm() { return 1; }
            configure_approved_resources
        """)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("操作已取消", result.stderr)

    def test_memory_shortage_allows_confirmation_without_lowering_approval(self):
        for decision, success in ((0, True), (1, False)):
            result = self.run_script(f"""
                MEMORY_GIB=32; HOST_MEM_TOTAL_KIB=16777216
                RUNNING_MEMORY_BYTES=1073741824; MEMORY_ALLOCATION_UNKNOWN=0
                confirm() {{ return {decision}; }}
                check_approved_memory
                printf '%s' "$MEMORY_GIB"
            """)
            self.assertEqual(result.returncode == 0, success)
            self.assertIn("内存分配不足", result.stderr)
            if success:
                self.assertEqual(result.stdout, "32")

    def test_duplicate_token_detects_stopped_container(self):
        result = self.run_script(r"""
            agent_token=cda_used
            docker() {
                if [[ "$1" == ps && "$2" == -aq ]]; then printf 'stopped\n'; return; fi
                case "$3" in
                    '{{range .Config.Env}}{{println .}}{{end}}') printf 'COMPUTEDOCK_TOKEN=cda_used\n';;
                    '{{.Name}}') printf '/old-training\n';;
                esac
            }
            check_existing_request_container
        """)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("old-training", result.stderr)

    def test_final_check_rejects_changed_approval(self):
        result = self.run_script(r"""
            APPROVED_REQUEST_ID=original; APPROVED_GPU_COUNT=1
            APPROVED_CPU_CORES=8; APPROVED_MEMORY_GIB=32
            fetch_approved_allocation() { printf 'original 1 16 32\n'; }
            verify_approved_allocation
        """)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("申请额度已变更", result.stderr)

    def test_report_flow_asks_mode_address_token_before_resources(self):
        result = self.run_script(r"""
            load_configuration() { :; }
            require_interactive_terminal() { :; }
            check_prerequisites() { :; }
            prompt_agent_mode() { AGENT_MODE=report; printf 'mode\n'; }
            prompt_agent_server_url() { printf 'address\n'; }
            normalize_agent_url() { :; }
            prompt_agent_token() { printf 'token\n'; }
            load_approved_allocation() { printf 'allocation\n'; }
            detect_host_resources() { :; }
            show_resource_snapshot() { :; }
            configure_approved_resources() { printf 'resources\n'; exit 0; }
            main
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["mode", "address", "token", "allocation", "resources"],
        )

    def test_test_mode_does_not_query_remote_service(self):
        result = self.run_script(r"""
            load_configuration() { :; }
            require_interactive_terminal() { :; }
            check_prerequisites() { :; }
            prompt_agent_mode() { AGENT_MODE=test; printf 'mode\n'; }
            prompt_agent_server_url() { exit 98; }
            load_approved_allocation() { exit 99; }
            detect_host_resources() { :; }
            show_resource_snapshot() { :; }
            prompt_gpus() { printf 'gpu\n'; }
            prompt_cpus() { printf 'cpu\n'; }
            prompt_memory() { printf 'memory\n'; exit 0; }
            main
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["mode", "gpu", "cpu", "memory"])

#!/bin/bash

set -u
set -o pipefail

readonly SUPERVISOR_CONFIG="/etc/supervisor/supervisord.conf"
readonly PID_FILE="/run/computedock-agent/agent.pid"
readonly AGENT_EXECUTABLE="/opt/computedock-agent/venv/bin/computedock-agent"

program_is_running() {
    local program="$1"
    /usr/bin/supervisorctl -c "$SUPERVISOR_CONFIG" status "$program" 2>/dev/null \
        | awk '$2 == "RUNNING" { found = 1 } END { exit !found }'
}

program_is_running sshd || exit 1
program_is_running computedock-agent || exit 1

[[ -r "$PID_FILE" ]] || exit 1
IFS= read -r agent_pid < "$PID_FILE"
[[ "$agent_pid" =~ ^[0-9]+$ ]] || exit 1
kill -0 "$agent_pid" 2>/dev/null || exit 1

[[ -r "/proc/${agent_pid}/cmdline" ]] || exit 1
command_line=$(tr '\0' ' ' < "/proc/${agent_pid}/cmdline")
[[ "$command_line" == *"${AGENT_EXECUTABLE} run"* ]] || exit 1

exit 0

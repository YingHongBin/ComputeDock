#!/bin/bash

set -u
set -o pipefail

readonly AGENT_EXECUTABLE="/opt/computedock-agent/venv/bin/computedock-agent"
readonly TEST_OUTPUT_PATH="/opt/computedock-agent/test-samples.jsonl"
readonly RUNTIME_DIRECTORY="/run/computedock-agent"
readonly PID_FILE="${RUNTIME_DIRECTORY}/agent.pid"
readonly RESTART_DELAY_SECONDS=5

agent_pid=""

remove_pid_file() {
    rm -f "$PID_FILE"
}

stop_agent() {
    if [[ -n "$agent_pid" ]] && kill -0 "$agent_pid" 2>/dev/null; then
        kill -TERM "$agent_pid" 2>/dev/null || true
        wait "$agent_pid" 2>/dev/null || true
    fi
    remove_pid_file
    exit 0
}

trap stop_agent INT TERM
trap remove_pid_file EXIT

mkdir -p "$RUNTIME_DIRECTORY" || exit 1

agent_arguments=(run)
if [[ -n "${COMPUTEDOCK_TEST_OUTPUT:-}" ]]; then
    agent_arguments+=(--test-output "$TEST_OUTPUT_PATH")
fi

while true; do
    "$AGENT_EXECUTABLE" "${agent_arguments[@]}" &
    agent_pid=$!

    temporary_pid_file="${PID_FILE}.${BASHPID}"
    if ! printf '%s\n' "$agent_pid" > "$temporary_pid_file" \
        || ! mv -f "$temporary_pid_file" "$PID_FILE"; then
        printf '%s\n' "cannot publish computedock-agent PID file" >&2
        kill -TERM "$agent_pid" 2>/dev/null || true
        wait "$agent_pid" 2>/dev/null || true
        exit 1
    fi

    wait "$agent_pid"
    status=$?
    agent_pid=""
    remove_pid_file

    case "$status" in
        0|2)
            exit "$status"
            ;;
        *)
            printf '%s\n' \
                "computedock-agent exited unexpectedly with status ${status}; restarting in ${RESTART_DELAY_SECONDS}s" \
                >&2
            sleep "$RESTART_DELAY_SECONDS"
            ;;
    esac
done

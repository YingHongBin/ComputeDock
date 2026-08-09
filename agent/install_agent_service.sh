#!/usr/bin/env bash

set -euo pipefail

readonly DEFAULT_SERVER_URL="https://nbdataxai.com/monitor/api/v1/agent/samples"
readonly DEFAULT_INTERVAL="15"
readonly AGENT_INSTALL_DIR="/opt/computedock-agent"
readonly AGENT_STATE_DIR="/var/lib/computedock-agent"
readonly AGENT_LOG_DIR="/var/log/computedock-agent"
readonly SUPERVISOR_CONFIG="/etc/supervisor/conf.d/computedock-agent.conf"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
AGENT_SOURCE="$SCRIPT_DIR"
AGENT_NAME=""
SERVER_URL="$DEFAULT_SERVER_URL"
INTERVAL="$DEFAULT_INTERVAL"
TOKEN=""
temporary_config=""

info() {
    printf '[INFO] %s\n' "$*"
}

warn() {
    printf '[WARN] %s\n' "$*" >&2
}

die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

cleanup() {
    if [[ -n "$temporary_config" && -f "$temporary_config" ]]; then
        rm -f -- "$temporary_config"
    fi
}

trap cleanup EXIT

usage() {
    cat <<'EOF'
用法：
  ./install_agent_service.sh --name <Agent 名称> --token <已通过算力申请 Token> [选项]

选项：
  --name <name>          Web 页面中的 Agent/容器名称（必填）
  --token <token>        已通过算力申请 Token（必填）
  --interval <seconds>   采集间隔，5–3600 秒（默认 15）
  --server-url <url>     完整数据上报地址
  --agent-source <path>  Agent Python 包源码目录（默认为脚本所在目录）
  -h, --help             显示帮助

说明：
  本脚本必须在目标算力容器内以 root 用户执行。
  Token 会以明文形式保存在权限为 0600 的 Supervisor 配置中。
EOF
}

require_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" ]] || die "$option 需要参数。"
}

reject_line_breaks() {
    local label="$1"
    local value="$2"
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || die "$label 不能包含换行符。"
}

parse_arguments() {
    while (( $# > 0 )); do
        case "$1" in
            --name)
                require_value "$1" "${2:-}"
                AGENT_NAME="$2"
                shift 2
                ;;
            --token)
                require_value "$1" "${2:-}"
                TOKEN="$2"
                shift 2
                ;;
            --interval)
                require_value "$1" "${2:-}"
                INTERVAL="$2"
                shift 2
                ;;
            --server-url)
                require_value "$1" "${2:-}"
                SERVER_URL="$2"
                shift 2
                ;;
            --agent-source)
                require_value "$1" "${2:-}"
                AGENT_SOURCE="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                die "未知参数：$1"
                ;;
        esac
    done

    [[ -n "$AGENT_NAME" ]] || die "必须指定 --name。"
    [[ -n "$TOKEN" ]] || die "必须指定 --token。"
    [[ "$INTERVAL" =~ ^[0-9]+$ ]] || die "--interval 必须是整数。"
    (( INTERVAL >= 5 && INTERVAL <= 3600 )) || die "--interval 必须为 5–3600 秒。"

    reject_line_breaks "Agent 名称" "$AGENT_NAME"
    reject_line_breaks "上报地址" "$SERVER_URL"
    reject_line_breaks "Token" "$TOKEN"
    reject_line_breaks "Agent 源码路径" "$AGENT_SOURCE"
}

check_prerequisites() {
    (( EUID == 0 )) || die "必须在容器内以 root 用户执行。"
    command -v apt-get >/dev/null 2>&1 || die "目标容器不支持 apt-get。"
    [[ -f "$AGENT_SOURCE/pyproject.toml" ]] \
        || die "未找到 Agent Python 包：$AGENT_SOURCE/pyproject.toml"
}

supervisor_quote() {
    local value="$1"
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    value=${value//%/%%}
    printf '"%s"' "$value"
}

install_dependencies_and_agent() {
    info "安装系统 Python 和 Supervisor。"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends python3 python3-venv supervisor

    python3 -c '
import sys
if not ((3, 10) <= sys.version_info[:2] < (3, 15)):
    raise SystemExit(
        f"computedock-agent requires Python 3.10-3.14, got {sys.version.split()[0]}"
    )
' || die "系统 Python 版本不符合要求。"

    info "创建独立 Python venv 并安装 computedock-agent。"
    python3 -m venv "$AGENT_INSTALL_DIR/venv"
    "$AGENT_INSTALL_DIR/venv/bin/python" -m pip install --upgrade pip
    "$AGENT_INSTALL_DIR/venv/bin/pip" install --force-reinstall "$AGENT_SOURCE"

    install -d -m 0755 "$AGENT_STATE_DIR" "$AGENT_LOG_DIR"
    install -d -m 0755 "$(dirname "$SUPERVISOR_CONFIG")"
}

create_supervisor_config() {
    local quoted_url quoted_name quoted_token
    quoted_url=$(supervisor_quote "$SERVER_URL")
    quoted_name=$(supervisor_quote "$AGENT_NAME")
    quoted_token=$(supervisor_quote "$TOKEN")
    temporary_config=$(mktemp) || die "无法创建临时 Supervisor 配置。"

    {
        printf '%s\n' '[program:computedock-agent]'
        printf 'command=%s/venv/bin/computedock-agent run --server-url %s --container-name %s --interval %s --token %s\n' \
            "$AGENT_INSTALL_DIR" "$quoted_url" "$quoted_name" "$INTERVAL" "$quoted_token"
        printf 'environment=COMPUTEDOCK_STATE_DIR="%s"\n' "$AGENT_STATE_DIR"
        printf '%s\n' 'autostart=true'
        printf '%s\n' 'autorestart=unexpected'
        printf '%s\n' 'exitcodes=0,2'
        printf '%s\n' 'startsecs=1'
        printf '%s\n' 'startretries=3'
        printf '%s\n' 'stopsignal=TERM'
        printf '%s\n' 'stopasgroup=true'
        printf '%s\n' 'killasgroup=true'
        printf '%s\n' 'stdout_logfile=/dev/null'
        printf '%s\n' 'redirect_stderr=false'
        printf 'stderr_logfile=%s/error.log\n' "$AGENT_LOG_DIR"
        printf '%s\n' 'stderr_logfile_maxbytes=10MB'
        printf '%s\n' 'stderr_logfile_backups=3'
    } > "$temporary_config"

    install -m 0600 "$temporary_config" "$SUPERVISOR_CONFIG"
}

start_service() {
    info "启动 Supervisor 和 computedock-agent。"
    if supervisorctl -c /etc/supervisor/supervisord.conf pid >/dev/null 2>&1; then
        supervisorctl -c /etc/supervisor/supervisord.conf reread
        supervisorctl -c /etc/supervisor/supervisord.conf update
    else
        supervisord -c /etc/supervisor/supervisord.conf
    fi

    sleep 2
    local status_output
    if ! status_output=$(supervisorctl -c /etc/supervisor/supervisord.conf \
        status computedock-agent 2>&1); then
        printf '%s\n' "$status_output" >&2
        die "computedock-agent 未成功启动。"
    fi
    printf '%s\n' "$status_output"
    [[ "$status_output" == *RUNNING* ]] || die "computedock-agent 未进入 RUNNING 状态。"
}

show_result() {
    printf '\nAgent 已安装并由 Supervisor 在容器内后台管理。\n'
    printf 'Agent 名称: %s\n' "$AGENT_NAME"
    printf 'Agent 上报地址: %s\n' "$SERVER_URL"
    printf 'Agent 采集间隔: %s 秒\n' "$INTERVAL"
    printf 'Agent 异常日志: %s/error.log\n' "$AGENT_LOG_DIR"
    printf '\n查看状态：\n'
    printf '%s\n' 'supervisorctl status computedock-agent'
    printf '\n查看异常日志：\n'
    printf 'tail -f %s/error.log\n' "$AGENT_LOG_DIR"
    printf '\n'

    local pid_one
    pid_one=$(ps -p 1 -o comm= 2>/dev/null | tr -d '[:space:]' || true)
    if [[ "$pid_one" != "supervisord" ]]; then
        warn "当前容器 PID 1 是 '${pid_one:-unknown}'，容器重启后需要在容器内再次执行："
        printf '%s\n' 'supervisord -c /etc/supervisor/supervisord.conf'
    fi
}

main() {
    parse_arguments "$@"
    check_prerequisites
    install_dependencies_and_agent
    create_supervisor_config
    start_service
    if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi >/dev/null 2>&1; then
        warn "容器内 nvidia-smi 执行失败，Agent 可能无法采集 GPU 数据。"
    fi
    show_result
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi

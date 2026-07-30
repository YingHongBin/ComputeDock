#!/usr/bin/env bash

set -u
set -o pipefail

readonly DEFAULT_SERVER_URL="https://nbdataxai.com/monitor/api/v1/agent/samples"
readonly DEFAULT_INTERVAL="15"
readonly AGENT_INSTALL_DIR="/opt/computedock-agent"
readonly AGENT_STATE_DIR="/var/lib/computedock-agent"
readonly AGENT_LOG_DIR="/var/log/computedock-agent"
readonly SUPERVISOR_CONFIG="/etc/supervisor/conf.d/computedock-agent.conf"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONTAINER_NAME=""
AGENT_NAME=""
SERVER_URL="$DEFAULT_SERVER_URL"
INTERVAL="$DEFAULT_INTERVAL"
TOKEN=""
temporary_directory=""

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
    if [[ -n "$temporary_directory" && -d "$temporary_directory" ]]; then
        rm -rf -- "$temporary_directory"
    fi
}

trap cleanup EXIT

usage() {
    cat <<'EOF'
用法：
  ./install_agent_service.sh --container <Docker 容器名> --token <算力资源 Token> [选项]

选项：
  --container <name>   已运行的目标 Docker 容器（必填）
  --token <token>      算力资源 Token（必填）
  --name <name>        Web 页面中的 Agent/容器名称（默认使用 Docker 容器名）
  --interval <seconds> 采集间隔，5–3600 秒（默认 15）
  --server-url <url>   完整数据上报地址
  -h, --help           显示帮助

说明：
  脚本必须在 ComputeDock 项目根目录中使用，并由宿主机执行。
  Token 会以明文形式保存在容器内的 Supervisor 配置中。
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
            --container)
                require_value "$1" "${2:-}"
                CONTAINER_NAME="$2"
                shift 2
                ;;
            --token)
                require_value "$1" "${2:-}"
                TOKEN="$2"
                shift 2
                ;;
            --name)
                require_value "$1" "${2:-}"
                AGENT_NAME="$2"
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
            -h|--help)
                usage
                exit 0
                ;;
            *)
                die "未知参数：$1"
                ;;
        esac
    done

    [[ -n "$CONTAINER_NAME" ]] || die "必须指定 --container。"
    [[ -n "$TOKEN" ]] || die "必须指定 --token。"
    [[ -n "$AGENT_NAME" ]] || AGENT_NAME="$CONTAINER_NAME"
    [[ "$INTERVAL" =~ ^[0-9]+$ ]] || die "--interval 必须是整数。"
    (( INTERVAL >= 5 && INTERVAL <= 3600 )) || die "--interval 必须为 5–3600 秒。"

    reject_line_breaks "Docker 容器名" "$CONTAINER_NAME"
    reject_line_breaks "Agent 名称" "$AGENT_NAME"
    reject_line_breaks "上报地址" "$SERVER_URL"
    reject_line_breaks "Token" "$TOKEN"
}

check_prerequisites() {
    command -v docker >/dev/null 2>&1 || die "未找到 docker 命令。"
    [[ -d "$SCRIPT_DIR/agent" ]] || die "未找到 Agent 源码目录：$SCRIPT_DIR/agent"
    docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1 \
        || die "Docker 容器 '$CONTAINER_NAME' 不存在。"
    local running
    running=$(docker inspect --format '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || true)
    [[ "$running" == "true" ]] || die "Docker 容器 '$CONTAINER_NAME' 未运行。"
}

supervisor_quote() {
    local value="$1"
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    value=${value//%/%%}
    printf '"%s"' "$value"
}

create_supervisor_config() {
    local config_path="$1"
    local quoted_url quoted_name quoted_token
    quoted_url=$(supervisor_quote "$SERVER_URL")
    quoted_name=$(supervisor_quote "$AGENT_NAME")
    quoted_token=$(supervisor_quote "$TOKEN")

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
    } > "$config_path"
}

install_agent() {
    info "将 Agent 源码复制到容器 '$CONTAINER_NAME'。"
    docker exec --user 0 "$CONTAINER_NAME" sh -c \
        'rm -rf /tmp/computedock-agent && mkdir -p /tmp/computedock-agent' \
        || die "无法准备容器内临时目录。"
    docker cp "$SCRIPT_DIR/agent/." "$CONTAINER_NAME:/tmp/computedock-agent/" \
        || die "复制 Agent 源码失败。"

    info "安装系统 Python、Supervisor 和独立 Agent venv。"
    docker exec --user 0 "$CONTAINER_NAME" sh -c '
        set -eu
        command -v apt-get >/dev/null 2>&1 || {
            printf "%s\n" "target container does not provide apt-get" >&2
            exit 1
        }
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y --no-install-recommends python3 python3-venv supervisor
        python3 -m venv /opt/computedock-agent/venv
        /opt/computedock-agent/venv/bin/python -m pip install --upgrade pip
        /opt/computedock-agent/venv/bin/pip install --force-reinstall /tmp/computedock-agent
        install -d -m 0755 /var/lib/computedock-agent /var/log/computedock-agent
    ' || die "容器内 Agent 安装失败。"
}

install_supervisor_config() {
    temporary_directory=$(mktemp -d) || die "无法创建临时目录。"
    local local_config="$temporary_directory/computedock-agent.conf"
    create_supervisor_config "$local_config"

    docker cp "$local_config" "$CONTAINER_NAME:/tmp/computedock-agent.conf" \
        || die "复制 Supervisor 配置失败。"
    docker exec --user 0 "$CONTAINER_NAME" \
        install -m 0600 /tmp/computedock-agent.conf "$SUPERVISOR_CONFIG" \
        || die "安装 Supervisor 配置失败。"
    docker exec --user 0 "$CONTAINER_NAME" rm -f /tmp/computedock-agent.conf \
        || warn "未能清理容器内临时 Supervisor 配置。"
}

start_service() {
    info "启动 Supervisor 和 computedock-agent。"
    if docker exec --user 0 "$CONTAINER_NAME" \
        supervisorctl -c /etc/supervisor/supervisord.conf pid >/dev/null 2>&1; then
        docker exec --user 0 "$CONTAINER_NAME" \
            supervisorctl -c /etc/supervisor/supervisord.conf reread \
            || die "Supervisor 读取配置失败。"
        docker exec --user 0 "$CONTAINER_NAME" \
            supervisorctl -c /etc/supervisor/supervisord.conf update \
            || die "Supervisor 更新配置失败。"
    else
        docker exec --user 0 "$CONTAINER_NAME" \
            supervisord -c /etc/supervisor/supervisord.conf \
            || die "Supervisor 启动失败。"
    fi

    sleep 2
    local status_output
    status_output=$(docker exec --user 0 "$CONTAINER_NAME" \
        supervisorctl -c /etc/supervisor/supervisord.conf \
        status computedock-agent 2>&1) || {
        printf '%s\n' "$status_output" >&2
        die "computedock-agent 未成功启动。"
    }
    printf '%s\n' "$status_output"
    [[ "$status_output" == *RUNNING* ]] || die "computedock-agent 未进入 RUNNING 状态。"
}

show_result() {
    printf '\nAgent 已安装并由 Supervisor 管理。\n'
    printf 'Docker 容器: %s\n' "$CONTAINER_NAME"
    printf 'Agent 名称: %s\n' "$AGENT_NAME"
    printf 'Agent 上报地址: %s\n' "$SERVER_URL"
    printf 'Agent 采集间隔: %s 秒\n' "$INTERVAL"
    printf 'Agent 异常日志: %s\n' "$AGENT_LOG_DIR/error.log"
    printf '\n查看状态：\n'
    printf 'docker exec %q supervisorctl status computedock-agent\n' "$CONTAINER_NAME"
    printf '\n查看异常日志：\n'
    printf 'docker exec %q tail -f %q\n' "$CONTAINER_NAME" "$AGENT_LOG_DIR/error.log"
    printf '\n'
    warn "容器重启后 PID 1 仍只会启动 sshd，需要再执行以下命令启动 Supervisor："
    printf 'docker exec %q supervisord -c /etc/supervisor/supervisord.conf\n' "$CONTAINER_NAME"
}

main() {
    parse_arguments "$@"
    check_prerequisites
    install_agent
    install_supervisor_config
    start_service
    if ! docker exec "$CONTAINER_NAME" nvidia-smi >/dev/null 2>&1; then
        warn "容器内 nvidia-smi 执行失败，Agent 可能无法采集 GPU 数据。"
    fi
    show_result
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi

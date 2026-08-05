#!/usr/bin/env bash

set -u
set -o pipefail

readonly IMAGE_DEFAULT="dilab-base:cuda-12.8-v4"
readonly AGENT_TEST_OUTPUT_PATH="/opt/computedock-agent/test-samples.jsonl"
readonly AGENT_SERVER_URL_DEFAULT="https://nbdataxai.com/monitor/api/v1/agent/samples"

password=""
agent_token=""
GPU_DATA=""
ONLINE_CPU_SPEC=""
ONLINE_CPU_CSV=""
HOST_MEM_TOTAL_KIB=""
AGENT_SERVER_URL="$AGENT_SERVER_URL_DEFAULT"
AGENT_INTERVAL=""
AGENT_MODE="report"

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
    password=""
    agent_token=""
    unset NEW_PWD 2>/dev/null || true
    unset COMPUTEDOCK_TOKEN 2>/dev/null || true
}

handle_interrupt() {
    printf '\n操作已取消。\n' >&2
    exit 130
}

trap cleanup EXIT
trap handle_interrupt INT TERM

confirm() {
    local prompt="$1"
    local answer

    printf '%s [y/N]: ' "$prompt"
    IFS= read -r answer || return 1
    case "$answer" in
        y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

require_interactive_terminal() {
    [[ -t 0 ]] || die "该脚本需要在交互式终端中运行。"
}

check_prerequisites() {
    command -v docker >/dev/null 2>&1 || die "未找到 docker 命令。"
    docker info >/dev/null 2>&1 || die "无法访问 Docker daemon，请检查 Docker 服务和当前用户权限。"
}

expand_number_ranges() {
    local value="$1"
    local item start end number
    local old_ifs="$IFS"

    [[ "$value" =~ ^[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$ ]] || return 1

    IFS=','
    for item in $value; do
        if [[ "$item" == *-* ]]; then
            start=${item%-*}
            end=${item#*-}
        else
            start=$item
            end=$item
        fi

        if (( ${#start} > 5 || ${#end} > 5 )); then
            IFS="$old_ifs"
            return 1
        fi
        start=$((10#$start))
        end=$((10#$end))
        (( start <= end )) || {
            IFS="$old_ifs"
            return 1
        }

        number=$start
        while (( number <= end )); do
            printf '%s\n' "$number"
            number=$((number + 1))
        done
    done
    IFS="$old_ifs"
}

numbers_to_csv() {
    sort -nu | awk 'BEGIN { first = 1 } { if (!first) printf ","; printf "%s", $0; first = 0 } END { if (!first) printf "\n" }'
}

numbers_to_cpu_spec() {
    sort -nu | awk '
        BEGIN { first = 1 }
        NR == 1 { range_start = previous = $1; next }
        $1 == previous + 1 { previous = $1; next }
        {
            emit_range()
            range_start = previous = $1
        }
        END {
            if (NR > 0) {
                emit_range()
                printf "\n"
            }
        }
        function emit_range() {
            if (!first) printf ","
            if (range_start == previous) printf "%s", range_start
            else printf "%s-%s", range_start, previous
            first = 0
        }
    '
}

detect_host_resources() {
    if [[ -r /sys/devices/system/cpu/online ]]; then
        IFS= read -r ONLINE_CPU_SPEC < /sys/devices/system/cpu/online
    elif command -v lscpu >/dev/null 2>&1; then
        ONLINE_CPU_SPEC=$(lscpu -p=CPU,ONLINE 2>/dev/null | awk -F, '$1 !~ /^#/ && ($2 == "Y" || $2 == "") { print $1 }' | numbers_to_cpu_spec)
    elif command -v nproc >/dev/null 2>&1; then
        local cpu_count
        cpu_count=$(nproc)
        (( cpu_count > 0 )) || die "无法检测在线 CPU。"
        ONLINE_CPU_SPEC="0-$((cpu_count - 1))"
    else
        die "无法检测在线 CPU（需要 /sys、lscpu 或 nproc）。"
    fi

    ONLINE_CPU_SPEC=$(expand_number_ranges "$ONLINE_CPU_SPEC" | numbers_to_cpu_spec) || die "无法解析在线 CPU 列表：$ONLINE_CPU_SPEC"
    ONLINE_CPU_CSV=$(expand_number_ranges "$ONLINE_CPU_SPEC" | numbers_to_csv) || die "无法解析在线 CPU 列表：$ONLINE_CPU_SPEC"
    [[ -n "$ONLINE_CPU_CSV" ]] || die "未检测到在线 CPU。"

    if [[ -r /proc/meminfo ]]; then
        HOST_MEM_TOTAL_KIB=$(awk '$1 == "MemTotal:" { print $2; exit }' /proc/meminfo)
    elif command -v sysctl >/dev/null 2>&1; then
        local mem_bytes
        mem_bytes=$(sysctl -n hw.memsize 2>/dev/null || true)
        if [[ "$mem_bytes" =~ ^[0-9]+$ ]]; then
            HOST_MEM_TOTAL_KIB=$((mem_bytes / 1024))
        fi
    fi

    if command -v nvidia-smi >/dev/null 2>&1; then
        GPU_DATA=$(nvidia-smi \
            --query-gpu=index,uuid,name,memory.total \
            --format=csv,noheader,nounits 2>/dev/null || true)
    fi
}

format_kib_as_gib() {
    local kib="$1"
    awk -v kib="$kib" 'BEGIN { printf "%.1f GiB", kib / 1024 / 1024 }'
}

format_bytes() {
    local bytes="$1"
    if [[ ! "$bytes" =~ ^[0-9]+$ ]]; then
        printf '%s\n' "不可用"
    elif (( bytes == 0 )); then
        printf '%s\n' "未限制"
    elif (( bytes % 1073741824 == 0 )); then
        printf '%s GiB\n' "$((bytes / 1073741824))"
    elif (( bytes % 1048576 == 0 )); then
        printf '%s MiB\n' "$((bytes / 1048576))"
    else
        awk -v bytes="$bytes" 'BEGIN { printf "%.2f MiB\n", bytes / 1048576 }'
    fi
}

trim_whitespace() {
    sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

gpu_uuid_to_index() {
    local wanted_uuid="$1"
    local gpu_index gpu_uuid rest

    while IFS=',' read -r gpu_index gpu_uuid rest; do
        gpu_index=$(printf '%s' "$gpu_index" | trim_whitespace)
        gpu_uuid=$(printf '%s' "$gpu_uuid" | trim_whitespace)
        if [[ "$gpu_uuid" == "$wanted_uuid" ]]; then
            printf '%s\n' "$gpu_index"
            return 0
        fi
    done <<< "$GPU_DATA"
    return 1
}

normalize_gpu_devices() {
    local value="$1"
    local device mapped result=""
    local old_ifs="$IFS"

    value=$(printf '%s' "$value" | tr -d '[:space:]')
    IFS=','
    for device in $value; do
        [[ -n "$device" ]] || continue
        mapped="$device"
        if [[ "$device" == GPU-* ]]; then
            mapped=$(gpu_uuid_to_index "$device" || printf '%s' "$device")
        elif [[ "$device" =~ ^[0-9]+$ ]] && (( ${#device} <= 5 )); then
            mapped=$((10#$device))
        fi
        case ",$result," in
            *",$mapped,"*) ;;
            *)
                [[ -n "$result" ]] && result="${result},"
                result="${result}${mapped}"
                ;;
        esac
    done
    IFS="$old_ifs"
    printf '%s\n' "$result"
}

container_gpu_binding() {
    local container_id="$1"
    local value counts env_lines env_value="" count

    if ! value=$(docker inspect --format '{{range .HostConfig.DeviceRequests}}{{if .DeviceIDs}}{{join .DeviceIDs ","}}{{else}}all{{end}}{{end}}' "$container_id" 2>/dev/null); then
        warn "无法读取容器 $container_id 的 GPU 配置。"
        printf '%s\n' "无法识别"
        return
    fi
    value=$(printf '%s' "$value" | tr -d '[:space:]')

    if [[ -n "$value" && "$value" != "all" ]]; then
        normalize_gpu_devices "$value"
        return
    fi

    if [[ "$value" == "all" ]]; then
        counts=$(docker inspect --format '{{range .HostConfig.DeviceRequests}}{{if not .DeviceIDs}}{{println .Count}}{{end}}{{end}}' "$container_id" 2>/dev/null || true)
        count=$(printf '%s\n' "$counts" | awk '$1 < 0 { all = 1 } $1 > 0 { total += $1 } END { if (all) print -1; else if (total > 0) print total }')
        if [[ "$count" =~ ^[0-9]+$ ]] && (( count > 0 )); then
            printf '%s张（未指定）\n' "$count"
        else
            printf '%s\n' "all"
        fi
        return
    fi

    if ! env_lines=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container_id" 2>/dev/null); then
        warn "无法读取容器 $container_id 的 NVIDIA_VISIBLE_DEVICES。"
        printf '%s\n' "无法识别"
        return
    fi
    env_value=$(printf '%s\n' "$env_lines" | sed -n 's/^NVIDIA_VISIBLE_DEVICES=//p' | tail -n 1)
    case "$env_value" in
        ""|none|void) printf '%s\n' "-" ;;
        all) printf '%s\n' "all" ;;
        *) normalize_gpu_devices "$env_value" ;;
    esac
}

show_resource_snapshot() {
    local ids id name cpus compact_cpus gpus memory_bytes shm_bytes memory_limit shm_limit

    printf '\n========== 宿主机资源快照 =========='
    printf '\n在线 CPU: %s\n' "$ONLINE_CPU_SPEC"
    if [[ -n "$HOST_MEM_TOTAL_KIB" ]]; then
        printf '总内存: %s\n' "$(format_kib_as_gib "$HOST_MEM_TOTAL_KIB")"
    else
        printf '内存信息: 无法检测\n'
    fi

    if [[ -n "$GPU_DATA" ]]; then
        printf '\nGPU 容量：\n'
        printf '%-6s %-28s %-12s\n' "编号" "型号" "总显存"
        while IFS=',' read -r gpu_index gpu_uuid gpu_name gpu_total; do
            gpu_index=$(printf '%s' "$gpu_index" | trim_whitespace)
            gpu_name=$(printf '%s' "$gpu_name" | trim_whitespace)
            gpu_total=$(printf '%s' "$gpu_total" | trim_whitespace)
            printf '%-6s %-28.28s %-12s\n' "$gpu_index" "$gpu_name" "${gpu_total} MiB"
        done <<< "$GPU_DATA"
    else
        printf '\nGPU 容量：未检测到 NVIDIA GPU，或 nvidia-smi 不可用。\n'
    fi

    printf '\n运行中容器的资源分配：\n'
    printf '%-24s %-16s %-24s %-14s %-14s\n' "容器" "CPU 核" "GPU" "内存上限" "共享内存"
    ids=$(docker ps -q)
    if [[ -z "$ids" ]]; then
        printf '%s\n' "（当前没有运行中的容器）"
    else
        while IFS= read -r id; do
            [[ -n "$id" ]] || continue
            name=$(docker inspect --format '{{.Name}}' "$id" 2>/dev/null | sed 's#^/##')
            cpus=$(docker inspect --format '{{.HostConfig.CpusetCpus}}' "$id" 2>/dev/null || true)
            if [[ -n "$cpus" ]]; then
                compact_cpus=$(expand_number_ranges "$cpus" 2>/dev/null | numbers_to_cpu_spec) || compact_cpus="$cpus"
                cpus="$compact_cpus"
            else
                cpus="全部/未限制"
            fi
            gpus=$(container_gpu_binding "$id")
            memory_bytes=$(docker inspect --format '{{.HostConfig.Memory}}' "$id" 2>/dev/null || true)
            shm_bytes=$(docker inspect --format '{{.HostConfig.ShmSize}}' "$id" 2>/dev/null || true)
            memory_limit=$(format_bytes "$memory_bytes")
            shm_limit=$(format_bytes "$shm_bytes")
            printf '%-24.24s %-16.16s %-24.24s %-14.14s %-14.14s\n' "$name" "$cpus" "$gpus" "$memory_limit" "$shm_limit"
        done <<< "$ids"
    fi
    printf '%s\n\n' "===================================="
}

prompt_username() {
    local value
    while true; do
        printf '容器用户名: '
        IFS= read -r value || exit 1
        if [[ "$value" =~ ^[a-z][a-z0-9_-]*$ ]]; then
            USERNAME_VALUE="$value"
            return
        fi
        warn "用户名必须以小写字母开头，且只能包含小写字母、数字、下划线和连字符。"
    done
}

prompt_password() {
    local first second
    while true; do
        printf '容器用户密码: '
        IFS= read -r first || exit 1
        printf '再次输入密码: '
        IFS= read -r second || exit 1
        if [[ -z "$first" ]]; then
            warn "密码不能为空。"
        elif [[ "$first" != "$second" ]]; then
            warn "两次输入的密码不一致。"
        else
            password="$first"
            first=""
            second=""
            return
        fi
        first=""
        second=""
    done
}

prompt_container_name() {
    local value
    while true; do
        printf '容器名称 [%s]: ' "$USERNAME_VALUE"
        IFS= read -r value || exit 1
        [[ -n "$value" ]] || value="$USERNAME_VALUE"
        if [[ ! "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
            warn "容器名必须以字母或数字开头，且只能包含字母、数字、下划线、点和连字符。"
            continue
        fi
        if docker container inspect "$value" >/dev/null 2>&1; then
            warn "容器名 '$value' 已存在，请重新输入。"
            continue
        fi
        CONTAINER_NAME="$value"
        return
    done
}

prompt_image() {
    local value
    while true; do
        printf 'Docker 镜像 [%s]: ' "$IMAGE_DEFAULT"
        IFS= read -r value || exit 1
        [[ -n "$value" ]] || value="$IMAGE_DEFAULT"
        if docker image inspect "$value" >/dev/null 2>&1; then
            IMAGE_VALUE="$value"
            return
        fi
        warn "本地镜像 '$value' 不存在；脚本不会自动拉取镜像。"
    done
}

prompt_agent_server_url() {
    local value
    printf 'Agent 完整上报地址 [%s]: ' "$AGENT_SERVER_URL_DEFAULT"
    IFS= read -r value || exit 1
    AGENT_SERVER_URL="${value:-$AGENT_SERVER_URL_DEFAULT}"
}

prompt_agent_mode() {
    local value
    while true; do
        printf 'Agent 运行模式（report=远程上报，test=写入本地文件）[report]: '
        IFS= read -r value || exit 1
        [[ -n "$value" ]] || value="report"
        case "$value" in
            report|test)
                AGENT_MODE="$value"
                return
                ;;
            *)
                warn "Agent 运行模式只能是 report 或 test。"
                ;;
        esac
    done
}

prompt_agent_interval() {
    local value
    while true; do
        printf 'Agent 采集间隔（秒）[15]: '
        IFS= read -r value || exit 1
        [[ -n "$value" ]] || value="15"
        if [[ ! "$value" =~ ^[0-9]+$ ]] || (( ${#value} > 4 )); then
            warn "采集间隔必须是 5 到 3600 之间的整数。"
            continue
        fi
        value=$((10#$value))
        if (( value < 5 || value > 3600 )); then
            warn "采集间隔必须是 5 到 3600 之间的整数。"
            continue
        fi
        AGENT_INTERVAL="$value"
        return
    done
}

prompt_agent_token() {
    local value
    while true; do
        printf '算力资源 Token: '
        IFS= read -r value || exit 1
        if [[ -n "$value" ]]; then
            agent_token="$value"
            return
        fi
        warn "算力资源 Token 不能为空。"
    done
}

prompt_mount_path() {
    local value
    while true; do
        printf '宿主机挂载目录（绝对路径）: '
        IFS= read -r value || exit 1
        if [[ "$value" != /* ]]; then
            warn "挂载目录必须是绝对路径。"
        elif [[ ! -d "$value" ]]; then
            warn "目录 '$value' 不存在，请先创建后再输入。"
        else
            MOUNT_PATH="$value"
            return
        fi
    done
}

prompt_memory() {
    local value requested_kib
    while true; do
        printf '容器内存上限（GiB，仅输入正整数）: '
        IFS= read -r value || exit 1
        if [[ ! "$value" =~ ^[0-9]+$ ]]; then
            warn "内存必须是大于 0 的整数。"
            continue
        fi
        if (( ${#value} > 7 )) || (( 10#$value > 1048576 )); then
            warn "内存数值过大，请重新输入。"
            continue
        fi
        if (( 10#$value <= 0 )); then
            warn "内存必须是大于 0 的整数。"
            continue
        fi
        MEMORY_GIB=$((10#$value))
        requested_kib=$((MEMORY_GIB * 1024 * 1024))
        if [[ -n "$HOST_MEM_TOTAL_KIB" ]] && (( requested_kib > HOST_MEM_TOTAL_KIB )); then
            warn "请求的 ${MEMORY_GIB} GiB 超过宿主机总内存 $(format_kib_as_gib "$HOST_MEM_TOTAL_KIB")。"
            confirm "仍要使用该内存上限吗？" || continue
        fi
        SHM_MIB=$((MEMORY_GIB * 512))
        return
    done
}

gpu_index_exists() {
    local wanted="$1"
    local index uuid rest
    while IFS=',' read -r index uuid rest; do
        index=$(printf '%s' "$index" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
        [[ "$index" == "$wanted" ]] && return 0
    done <<< "$GPU_DATA"
    return 1
}

prompt_gpus() {
    local value normalized index raw_index invalid
    while true; do
        printf 'GPU 编号（如 0,1；留空表示不使用 GPU）: '
        IFS= read -r value || exit 1
        value=$(printf '%s' "$value" | tr -d '[:space:]')
        if [[ -z "$value" ]]; then
            GPU_SELECTION=""
            return
        fi
        if [[ "$value" == "all" ]]; then
            warn "不允许使用 all，请显式输入 GPU 编号。"
            continue
        fi
        if [[ ! "$value" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
            warn "GPU 编号格式无效，应为 0 或 0,1 这样的数字列表。"
            continue
        fi
        invalid=""
        while IFS= read -r raw_index; do
            (( ${#raw_index} <= 5 )) || invalid="$raw_index"
        done < <(printf '%s\n' "$value" | tr ',' '\n')
        if [[ -n "$invalid" ]]; then
            warn "GPU 编号过大：$invalid。"
            continue
        fi
        normalized=$(printf '%s\n' "${value//,/$'\n'}" | awk '{ print $1 + 0 }' | numbers_to_csv)
        if [[ -n "$GPU_DATA" ]]; then
            invalid=""
            while IFS= read -r index; do
                gpu_index_exists "$index" || invalid="$index"
            done < <(printf '%s\n' "$normalized" | tr ',' '\n')
            if [[ -n "$invalid" ]]; then
                warn "GPU 编号 $invalid 不存在。"
                continue
            fi
        else
            warn "无法通过 nvidia-smi 验证 GPU 编号，将按手动输入继续。"
        fi
        GPU_SELECTION="$normalized"
        return
    done
}

online_cpu_exists() {
    local wanted="$1"
    case ",$ONLINE_CPU_CSV," in
        *",$wanted,"*) return 0 ;;
        *) return 1 ;;
    esac
}

prompt_cpus() {
    local value normalized cpu invalid
    while true; do
        printf 'CPU 核（如 0-15、0,2,4 或 0-3,8-11）: '
        IFS= read -r value || exit 1
        value=$(printf '%s' "$value" | tr -d '[:space:]')
        normalized=$(expand_number_ranges "$value" 2>/dev/null | numbers_to_cpu_spec) || normalized=""
        if [[ -z "$normalized" ]]; then
            warn "CPU 核格式无效，且至少需要指定一个在线 CPU。"
            continue
        fi
        invalid=""
        while IFS= read -r cpu; do
            online_cpu_exists "$cpu" || invalid="$cpu"
        done < <(expand_number_ranges "$normalized")
        if [[ -n "$invalid" ]]; then
            warn "CPU $invalid 不在线；当前在线 CPU 为 ${ONLINE_CPU_SPEC}。"
            continue
        fi
        CPU_SELECTION="$normalized"
        return
    done
}

port_is_in_use() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        if ss -H -ltn 2>/dev/null | awk -v wanted="$port" '{ address=$4; sub(/^.*:/, "", address); if (address == wanted) found=1 } END { exit !found }'; then
            return 0
        fi
    fi
    [[ -n "$(docker ps -a --filter "publish=$port" -q 2>/dev/null)" ]]
}

prompt_port() {
    local value
    while true; do
        printf 'SSH 宿主机端口（必须手动输入）: '
        IFS= read -r value || exit 1
        if [[ ! "$value" =~ ^[0-9]+$ ]] || (( ${#value} > 5 )); then
            warn "端口必须是 1 到 65535 之间的整数。"
            continue
        fi
        if (( 10#$value < 1 || 10#$value > 65535 )); then
            warn "端口必须是 1 到 65535 之间的整数。"
            continue
        fi
        value=$((10#$value))
        if port_is_in_use "$value"; then
            warn "端口 $value 已被监听或已映射给 Docker 容器。"
            continue
        fi
        SSH_PORT="$value"
        return
    done
}

csv_sets_overlap() {
    local left="$1"
    local right="$2"
    local item

    while IFS= read -r item; do
        case ",$right," in
            *",$item,"*) return 0 ;;
        esac
    done < <(printf '%s\n' "$left" | tr ',' '\n')
    return 1
}

check_resource_conflicts() {
    local ids id name cpus compact_cpus selected_cpus expanded_cpus gpus conflict=0 details=""
    ids=$(docker ps -q)
    [[ -n "$ids" ]] || return 1
    selected_cpus=$(expand_number_ranges "$CPU_SELECTION" | numbers_to_csv)

    while IFS= read -r id; do
        [[ -n "$id" ]] || continue
        name=$(docker inspect --format '{{.Name}}' "$id" 2>/dev/null | sed 's#^/##')
        cpus=$(docker inspect --format '{{.HostConfig.CpusetCpus}}' "$id" 2>/dev/null || true)
        if [[ -z "$cpus" ]]; then
            details="${details}\n  - CPU 与容器 ${name} 重叠（该容器未限制 CPU）"
            conflict=1
        else
            compact_cpus=$(expand_number_ranges "$cpus" 2>/dev/null | numbers_to_cpu_spec) || compact_cpus="$cpus"
            expanded_cpus=$(expand_number_ranges "$compact_cpus" 2>/dev/null | numbers_to_csv || true)
            if [[ -n "$expanded_cpus" ]] && csv_sets_overlap "$selected_cpus" "$expanded_cpus"; then
                details="${details}\n  - CPU 与容器 ${name} 重叠（${compact_cpus}）"
                conflict=1
            fi
        fi

        if [[ -n "$GPU_SELECTION" ]]; then
            gpus=$(container_gpu_binding "$id")
            if [[ "$gpus" != "-" && ! "$gpus" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
                details="${details}\n  - GPU 与容器 ${name} 存在潜在重叠（${gpus}）"
                conflict=1
            elif [[ "$gpus" != "-" ]] && csv_sets_overlap "$GPU_SELECTION" "$gpus"; then
                details="${details}\n  - GPU 与容器 ${name} 重叠（${gpus}）"
                conflict=1
            fi
        fi
    done <<< "$ids"

    if (( conflict )); then
        warn "检测到资源重叠："
        printf '%b\n' "$details" >&2
        return 0
    fi
    return 1
}

print_command_preview() {
    local argument
    printf '\n将执行以下命令：\n'
    printf 'NEW_PWD=%q ' "$password"
    if [[ "$AGENT_MODE" == "report" ]]; then
        printf 'COMPUTEDOCK_TOKEN=%q ' "$agent_token"
    fi
    for argument in "${DOCKER_COMMAND[@]}"; do
        printf '%q ' "$argument"
    done
    printf '\n\n'
}

show_configuration() {
    printf '\n========== 创建配置 =========='
    printf '\n容器名称: %s\n' "$CONTAINER_NAME"
    printf '镜像: %s\n' "$IMAGE_VALUE"
    printf '用户: %s\n' "$USERNAME_VALUE"
    printf '用户密码: %s\n' "$password"
    printf 'GPU: %s\n' "${GPU_SELECTION:-不使用}"
    printf 'CPU 核: %s\n' "$CPU_SELECTION"
    printf '内存: %sG\n' "$MEMORY_GIB"
    printf '共享内存: %sM\n' "$SHM_MIB"
    printf 'SSH 端口: %s -> 22\n' "$SSH_PORT"
    printf '挂载: %s -> /home/%s\n' "$MOUNT_PATH" "$USERNAME_VALUE"
    printf 'Agent 名称: %s\n' "$CONTAINER_NAME"
    printf 'Agent 运行模式: %s\n' "$AGENT_MODE"
    printf 'Agent 采集间隔: %s 秒\n' "$AGENT_INTERVAL"
    if [[ "$AGENT_MODE" == "report" ]]; then
        printf 'Agent 上报地址: %s\n' "$AGENT_SERVER_URL"
        printf 'Agent Token: %s\n' "$agent_token"
    else
        printf 'Agent 测试输出: %s\n' "$AGENT_TEST_OUTPUT_PATH"
    fi
    printf '%s\n' "=============================="
}

build_docker_command() {
    DOCKER_COMMAND=(docker run -itd)
    if [[ -n "$GPU_SELECTION" ]]; then
        DOCKER_COMMAND+=(--gpus "\"device=${GPU_SELECTION}\"")
    else
        # CUDA base images commonly default NVIDIA_VISIBLE_DEVICES to "all".
        # Explicitly disable the NVIDIA runtime injection for CPU-only containers.
        DOCKER_COMMAND+=(-e "NVIDIA_VISIBLE_DEVICES=void")
    fi
    DOCKER_COMMAND+=(
        --cpuset-cpus "$CPU_SELECTION"
        -m "${MEMORY_GIB}G"
        --memory-swap "${MEMORY_GIB}G"
        --shm-size="${SHM_MIB}M"
        --ulimit memlock=-1:-1
        -p "${SSH_PORT}:22"
        -e "NEW_USER=${USERNAME_VALUE}"
        -e NEW_PWD
        -e "COMPUTEDOCK_CONTAINER_NAME=${CONTAINER_NAME}"
        -e "COMPUTEDOCK_INTERVAL=${AGENT_INTERVAL}"
        -e "COMPUTEDOCK_STATE_DIR=/var/lib/computedock-agent"
    )
    if [[ "$AGENT_MODE" == "report" ]]; then
        DOCKER_COMMAND+=(
            -e "COMPUTEDOCK_SERVER_URL=${AGENT_SERVER_URL}"
            -e COMPUTEDOCK_TOKEN
        )
    else
        DOCKER_COMMAND+=(
            -e "COMPUTEDOCK_TEST_OUTPUT=1"
        )
    fi
    DOCKER_COMMAND+=(
        -v "${MOUNT_PATH}:/home/${USERNAME_VALUE}"
        --name "$CONTAINER_NAME"
        "$IMAGE_VALUE"
    )
}

wait_for_container_services() {
    local container_id="$1"
    local deadline running
    deadline=$((SECONDS + 10))

    while (( SECONDS < deadline )); do
        if docker exec "$container_id" \
            /usr/local/bin/healthcheck.sh >/dev/null 2>&1; then
            return 0
        fi
        running=$(docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null || true)
        [[ "$running" == "true" ]] || return 1
        sleep 1
    done
    return 1
}

create_container() {
    local container_id running

    if ! container_id=$(NEW_PWD="$password" COMPUTEDOCK_TOKEN="$agent_token" "${DOCKER_COMMAND[@]}"); then
        die "docker run 执行失败。"
    fi
    password=""
    agent_token=""
    unset NEW_PWD 2>/dev/null || true
    unset COMPUTEDOCK_TOKEN 2>/dev/null || true

    sleep 1
    running=$(docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null || true)
    if [[ "$running" != "true" ]]; then
        warn "容器已创建，但未保持运行。启动日志如下："
        docker logs "$container_id" 2>&1 || true
        die "容器启动失败；已保留停止状态的容器 '$CONTAINER_NAME' 供排查。"
    fi

    if ! wait_for_container_services "$container_id"; then
        warn "容器仍在运行，但 SSH 或 Agent 未在 10 秒内进入健康状态。"
        printf '%s\n' 'Supervisor 状态：' >&2
        docker exec "$container_id" \
            /usr/bin/supervisorctl \
            -c /etc/supervisor/supervisord.conf \
            status 2>&1 || true
        printf '%s\n' '容器日志：' >&2
        docker logs "$container_id" 2>&1 || true
        die "容器服务启动失败；已保留容器 '$CONTAINER_NAME' 供排查。"
    fi

    printf '\n容器创建成功。\n'
    printf '容器名称: %s\n' "$CONTAINER_NAME"
    printf '容器 ID: %.12s\n' "$container_id"
    printf 'SSH: ssh %s@<服务器地址> -p %s\n' "$USERNAME_VALUE" "$SSH_PORT"
    printf '挂载: %s -> /home/%s\n' "$MOUNT_PATH" "$USERNAME_VALUE"
    printf '资源: GPU=%s, CPU=%s, 内存=%sG, 共享内存=%sM\n' \
        "${GPU_SELECTION:-不使用}" "$CPU_SELECTION" "$MEMORY_GIB" "$SHM_MIB"
    if [[ "$AGENT_MODE" == "report" ]]; then
        warn "安全提示：容器管理员可通过容器配置查看 NEW_PWD 和 COMPUTEDOCK_TOKEN，请勿复用重要密码。"
    else
        printf '测试数据: docker exec %q tail -f %q\n' \
            "$CONTAINER_NAME" "$AGENT_TEST_OUTPUT_PATH"
    fi
}

main() {
    require_interactive_terminal
    check_prerequisites
    detect_host_resources
    show_resource_snapshot

    prompt_gpus
    prompt_cpus
    prompt_memory
    prompt_port
    prompt_username
    prompt_password
    prompt_mount_path
    prompt_container_name
    prompt_image
    prompt_agent_mode
    prompt_agent_interval
    if [[ "$AGENT_MODE" == "report" ]]; then
        prompt_agent_server_url
        prompt_agent_token
    fi

    show_configuration
    build_docker_command
    print_command_preview

    info "执行前重新检查运行中容器的资源绑定。"
    if check_resource_conflicts; then
        confirm "资源存在重叠，仍要继续吗？" || die "操作已取消。"
    else
        info "未发现与运行中容器的 GPU/CPU 绑定冲突。"
    fi

    if port_is_in_use "$SSH_PORT"; then
        die "端口 $SSH_PORT 在交互期间已被占用，请重新运行脚本。"
    fi
    if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
        die "容器名 '$CONTAINER_NAME' 在交互期间已被占用，请重新运行脚本。"
    fi
    docker image inspect "$IMAGE_VALUE" >/dev/null 2>&1 || die "镜像 '$IMAGE_VALUE' 在交互期间已不可用。"

    confirm "确认创建并启动容器吗？" || die "操作已取消。"
    create_container
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi

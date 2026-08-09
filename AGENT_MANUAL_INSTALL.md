# ComputeDock Agent 手动安装指南

本文档说明如何将 `computedock-agent` 手动安装到已有的算力 Docker 容器中，并配置 GPU 数据测试、正式上报、状态持久化和异常退出后自动重启。

## 1. 运行要求

- Linux 容器。
- Python 3.10–3.14。
- 容器通过 NVIDIA Container Toolkit 获得 GPU 访问权限。
- 容器包含 NVIDIA `utility` capability，能够访问 NVML。
- 能够访问数据上报地址。

先在容器内确认 GPU 可见：

```bash
nvidia-smi
```

如果该命令失败，应先检查宿主机 NVIDIA 驱动、NVIDIA Container Toolkit 以及容器的 `--gpus` 配置。

## 2. 复制 Agent 源码

在 ComputeDock 项目根目录执行：

```bash
docker cp ./agent <container-name>:/tmp/computedock-agent
docker exec -it <container-name> bash
```

将 `<container-name>` 替换为实际的 Docker 容器名称。

## 3. 安装独立 Python 环境

在算力容器内执行：

```bash
apt-get update
apt-get install -y python3 python3-venv

python3 -m venv /opt/computedock-agent/venv
/opt/computedock-agent/venv/bin/python -m pip install --upgrade pip
/opt/computedock-agent/venv/bin/pip install /tmp/computedock-agent
```

该 venv 位于 `/opt/computedock-agent/venv`，不会使用或修改容器中的 Conda 环境。

验证安装：

```bash
/opt/computedock-agent/venv/bin/computedock-agent --help
```

## 4. 配置状态目录

Agent 需要一个由调用方显式指定的状态目录：

```bash
mkdir -p /var/lib/computedock-agent
```

首次运行时，Agent 会将用户指定的容器名称写入：

```text
/var/lib/computedock-agent/identity.json
```

后续启动必须使用同一容器名称。如果传入其他名称，Agent 会拒绝启动。

Docker 容器普通重启不会删除该文件；如果容器会被删除后重建，则需要在创建容器时挂载独立命名卷：

```bash
-v computedock-agent-worker01:/var/lib/computedock-agent
```

已创建的容器无法直接追加 Docker 挂载，需要重建容器才能添加。

## 5. 使用测试模式验证采集

测试模式不发起 HTTP 请求，而是将有效样本逐行追加到 JSONL 文件：

```bash
COMPUTEDOCK_STATE_DIR=/var/lib/computedock-agent \
/opt/computedock-agent/venv/bin/computedock-agent run \
  --container-name 'worker-01' \
  --interval 15 \
  --test-output /tmp/computedock-samples.jsonl
```

在另一个终端中查看数据：

```bash
docker exec <container-name> tail -f /tmp/computedock-samples.jsonl
```

按 `Ctrl+C` 停止 Agent。如果容器中没有可见 GPU，Agent 不会写入空批次。

## 6. 正式上报

算力申请通过后，管理员在“算力申请”页面复制该申请的 Token，再执行：

```bash
COMPUTEDOCK_STATE_DIR=/var/lib/computedock-agent \
/opt/computedock-agent/venv/bin/computedock-agent run \
  --server-url 'https://nbdataxai.com/monitor/api/v1/agent/samples' \
  --container-name 'fanzhuoning' \
  --interval 15 \
  --token 'cda_xxx'
```

参数说明：

- `--server-url`：完整数据上报接口，Agent 不会自动追加路径。
- `--container-name`：在 Web 详情页中显示的容器名称。
- `--interval`：两次采集开始时间的间隔，可设置为 5–3600 秒的整数。
- `--token`：已通过算力申请的 Token，通过 Bearer 请求头发送。普通用户不能查看或复制 Token。

Agent 不校验上报地址的格式。每次请求超时为 10 秒。采集失败、无可见 GPU 或上报失败时，当前批次直接丢弃，不进行补传。

## 7. 使用 Supervisor 持久运行

普通 Docker 容器通常不以 systemd 作为 PID 1，因此容器内建议使用 Supervisor 管理 Agent。

对于 PID 1 为 `sshd` 的旧容器，先在 ComputeDock 项目根目录将 Agent 目录复制到容器：

```bash
docker cp ./agent worker-01:/tmp/computedock-agent
docker exec -it --user root worker-01 bash
```

然后在目标容器内执行：

```bash
chmod +x /tmp/computedock-agent/install_agent_service.sh
/tmp/computedock-agent/install_agent_service.sh \
  --name worker-01 \
  --interval 15 \
  --token '<approved-request-token>'
```

脚本会在当前容器内创建独立 venv、安装 Supervisor、写入服务配置并启动 Agent。`--name` 必须由用户显式指定。默认从脚本所在目录安装 Python 包；可以使用 `--agent-source` 指定其他路径。默认上报地址为 `https://nbdataxai.com/monitor/api/v1/agent/samples`。

如需手动完成同样的配置，继续按以下步骤操作。

安装 Supervisor：

```bash
apt-get update
apt-get install -y supervisor
```

新建 `/etc/supervisor/conf.d/computedock-agent.conf`：

```ini
[program:computedock-agent]
command=/opt/computedock-agent/venv/bin/computedock-agent run --server-url https://nbdataxai.com/monitor/api/v1/agent/samples --container-name worker-01 --interval 15 --token <approved-request-token>
environment=COMPUTEDOCK_STATE_DIR="/var/lib/computedock-agent"
autostart=true
autorestart=unexpected
exitcodes=0,2
startsecs=1
startretries=3
stopsignal=TERM
stopasgroup=true
killasgroup=true
stdout_logfile=/dev/null
redirect_stderr=false
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
```

载入配置：

```bash
supervisorctl reread
supervisorctl update
supervisorctl status computedock-agent
```

仅在运行中的容器内执行上述命令，并不能保证 Supervisor 在容器重建后自动启动。要获得完整的持久化行为，应将 Agent 安装、Supervisor 配置和 Supervisor 启动命令写入 Dockerfile 及容器入口流程。项目根目录的以下文件已实现该集成：

- `Dockerfile`
- `supervisord.conf`
- `run_agent_service.sh`
- `healthcheck.sh`

## 8. 查看日志

Agent 正常采集和上报时不记录日志，只将异常写入标准错误。

如果 Supervisor 将标准错误转发到 `/dev/stderr`，可在宿主机查看：

```bash
docker logs -f --tail=100 <container-name>
```

测试模式的数据不属于异常日志，需要直接查看 `--test-output` 指定的 JSONL 文件。

## 9. 常见问题

### Agent 没有上报任何数据

1. 在容器中执行 `nvidia-smi`，确认 GPU 可见。
2. 使用测试模式确认 NVML 能够采集数据。
3. 通过 `docker logs` 检查 HTTP 或 NVML 异常。
4. 确认上报地址包含完整的 `/monitor/api/v1/agent/samples` 路径。

### 返回 HTTP 401

确认 Token 与 Web 页面中已通过申请的 Token 完全一致。申请到期或关联用户、项目、资源被禁用后，已通过的 Token 仍会接受上报。

### 容器名称不一致

Agent 会持久化首次使用的容器名称。后续应继续使用同一名称，不要随意删除 `identity.json`，否则 Web 端可能将上报识别为另一个容器实例。

### HTTP 404

确认 `--server-url` 是完整数据接口，并检查 Nginx 是否将 `/monitor/api/v1/agent/samples` 转发到 Collector 服务。

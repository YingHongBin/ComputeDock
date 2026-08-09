# ComputeDock GPU 数据上报 Agent

`computedock-agent` 是安装在算力隔离容器内的 Python CLI。它只读取当前容器通过 NVIDIA Container Toolkit 可见的 GPU，采集 GPU UUID、显存和利用率，然后按固定周期批量上报。

Agent 不采集 CPU、系统内存、Docker 或宿主机信息，不访问 Docker Socket，也不支持 MIG。

## 安装

需要 Linux、Python 3.10–3.14，以及能够访问 NVML 的 NVIDIA 容器运行环境。容器应启用 NVIDIA `utility` capability。

在本目录执行：

```shell
python -m pip install .
```

也可以从项目根目录执行：

```shell
python -m pip install ./agent
```

## 正式运行

首次运行必须指定容器名称。名称会原样保存到 `$COMPUTEDOCK_STATE_DIR/identity.json`；后续可以省略，若传入不同名称则拒绝启动。调用方必须显式设置 `COMPUTEDOCK_STATE_DIR`，并自行决定是否持久化该目录。项目根 Docker 脚本会将它设置为 `/var/lib/computedock-agent`。

```shell
COMPUTEDOCK_STATE_DIR=/var/lib/computedock-agent computedock-agent run \
    --server-url 'https://monitor.example.com/api/v1/gpu/samples' \
    --container-name 'worker-01' \
    --interval 15 \
    --token 'approved-request-token'
```

`--server-url` 是完整数据接口地址，Agent 不会追加路径或限制协议。`--interval` 是两次采集开始时间的间隔，必须是 5–3600 秒的整数。Token 也可通过 `COMPUTEDOCK_TOKEN` 传入；命令行参数优先，但明文参数会出现在 Shell 历史和进程列表中。

除命令行参数外，支持以下环境变量：

```text
COMPUTEDOCK_SERVER_URL
COMPUTEDOCK_CONTAINER_NAME
COMPUTEDOCK_INTERVAL
COMPUTEDOCK_TOKEN
COMPUTEDOCK_STATE_DIR
```

每次请求对完整地址执行 `POST`，Token 放在 `Authorization: Bearer <token>` 请求头中。新部署应使用管理员从已通过算力申请中复制的 Token；升级前已有资源级 Token 仍可继续使用。请求体示例：

```json
{
  "container_name": "worker-01",
  "collected_at": "2026-07-29T10:30:00.000Z",
  "gpus": [
    {
      "gpuid": "GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "memory_used": 2048,
      "memory_total": 24576,
      "utilization": 37
    }
  ]
}
```

显存单位为 MiB，利用率为 0–100 的整数。请求超时固定为 10 秒。采集失败、没有可见 GPU 或 HTTP 上报失败时，本周期数据直接丢弃且不会重试；Agent 只把异常写入标准错误，正常周期不产生日志。

## 测试模式

测试模式不需要服务端地址和 Token，也不会发起 HTTP 请求。每次有效采样以一行 JSON 追加到指定文件：

```shell
COMPUTEDOCK_STATE_DIR=/tmp/computedock-agent-state computedock-agent run \
    --container-name 'worker-01' \
    --interval 15 \
    --test-output /tmp/computedock-samples.jsonl
```

文件不会被自动清空或轮转。没有可见 GPU 时不会写入空批次。

Python Agent 不提供默认状态目录或默认测试输出路径。调用方必须通过 `COMPUTEDOCK_STATE_DIR` 指定状态目录；测试模式必须通过 `--test-output` 指定输出文件。Docker 镜像中的目录约定由项目根目录脚本负责传入。

## Docker 镜像集成

Docker、Supervisor、健康检查和服务启动配置统一位于项目根目录；本目录只维护 Agent Python 包及其测试。集成和运行说明请参阅项目根目录的 `README.md`。

## 开发测试

在本目录执行：

```shell
python -m unittest discover -s tests -v
```

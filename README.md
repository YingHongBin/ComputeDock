# 基于 Docker 与 NVIDIA Container Toolkit 的算力隔离容器

为提升算力服务器的资源利用率与多用户使用效率，本文设计并实现了一套基于 Docker 与 NVIDIA Container Toolkit 的容器化算力隔离方案。该方案可实现 GPU 资源的按需分配、用户任务之间的算力隔离，并通过统一的基础镜像环境，保障了深度学习任务在共享服务器环境下的可复现性与稳定性。

GPU 数据上报 Agent 已独立放在 [`agent/`](agent/) 目录，安装和运行方式见 [`agent/README.md`](agent/README.md)。

Docker 运行集成文件统一位于项目根目录：

- `supervisord.conf`：管理 SSH 和 Agent 服务；
- `run_agent_service.sh`：保持 Agent 持久运行并处理异常重启；
- `healthcheck.sh`：检查 SSH、Supervisor 服务状态和 Agent 实际进程；
- `init_container.sh`：校验容器配置并启动 Supervisor。

`agent/` 目录只包含 Agent Python 实现、依赖约束和单元测试。

## 基础镜像环境介绍
镜像构建基底：
```
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04
```

镜像预安装组件如下：

- CUDA工具链（CUDA Toolkit/cuDNN），nvidia cuda镜像提供

- 包管理工具（conda），已换源ZJU mirror

> 推荐维护conda环境文件，新建容器后可以一键导入conda环境

- 系统工具（sudo/wget/curl/vim/git/openssh-server/openssh-client/tmux），apt安装，apt已换源ZJU mirror

- GPU 数据上报 Agent，使用 Ubuntu 系统 Python 的独立 venv，不依赖用户 Conda 环境

- Supervisor 作为容器 PID 1，同时管理 SSH 和 Agent 服务

## 容器构建

```shell
docker build -t dilab-base:cuda-12.8-v5 .
```

- 使用--gpus参数指定容器使用的具体GPU卡

- 使用--cpuset-cpus参数指定容器使用的特定cpu核

- 使用-m参数指定容器使用的内存限制

- 使用--shm-size参数指定容器共享内存大小，通常为内存的一半

> DataLoader设置--num_workers大于1时会启用多进程并行加载数据，加速训练数据的加载过程，提高 GPU 利用率。\
> 当使用多进程加载数据时，每个 worker 都可能：
> 1. 将数据缓存到 /dev/shm（共享内存）中；
> 2. 使用 multiprocessing 通信（也依赖 shared memory）；
> 3. PyTorch 的 tensor 默认支持共享内存以加速通信（pin_memory=True 时尤为明显）；<br>
>
> 因此，过小的共享内存配置可能导致Unexpected bus error encountered in worker. This might be caused by insufficient shared memory异常
- 通过 `-v <宿主机目录>:/home/<容器用户名>` 持久化容器用户的 home 目录

### 使用交互脚本创建容器

仓库提供 `create_container.sh`，用于交互式生成、确认并执行 `docker run` 命令：

```shell
chmod +x create_container.sh
./create_container.sh
```

镜像和数据根目录的默认值来自执行脚本时当前目录下的 `create_container.conf`：

```ini
IMAGE_DEFAULT=dilab-base:cuda-12.8-v5
DATA_ROOT_DEFAULT=/data
SSH_PORT_RANGE=50000-60000
```

配置文件为必需项；当前执行目录中不存在 `create_container.conf` 时，脚本会报错退出。配置文件只接受上述三个 `KEY=VALUE` 配置项，不会作为 Shell 代码执行。`SSH_PORT_RANGE` 使用 `起始端口-结束端口` 格式；脚本会避开宿主机监听端口和已有 Docker 容器映射端口，推荐范围内第一个可用端口，并将输入限制在该范围内。设为 `0` 时不限制范围，也不提供默认推荐值。可通过 `COMPUTEDOCK_CONFIG_FILE` 指定其他配置文件；单次执行还可使用 `COMPUTEDOCK_DEFAULT_IMAGE` 和 `COMPUTEDOCK_DATA_ROOT` 覆盖文件中的默认值。

脚本启动时会显示宿主机 GPU、CPU、内存的静态容量，以及运行中容器的 GPU/CPU 绑定、内存上限、共享内存和端口映射，不采集实时使用率。端口按 `宿主机端口->容器端口/协议` 展示；没有映射时显示 `-`。随后依次输入 GPU（可留空）、CPU 核、内存上限、SSH 端口、容器用户、密码、容器名、宿主机数据根目录、镜像、Agent 运行模式和采集间隔。Agent 名称自动使用 Docker 容器名。

GPU 留空时，脚本会显式设置 `NVIDIA_VISIBLE_DEVICES=void`，确保 CUDA 基础镜像或 Docker 的 NVIDIA 默认运行时不会让容器看到宿主机 GPU。Agent 仍会正常运行并通过健康检查，但会静默跳过 GPU 采集。修复前以 GPU 留空方式创建的容器不会自动更新，需要删除并重新创建后才能获得该隔离配置。

Agent 支持两种容器运行模式：`report` 模式继续输入完整上报地址和算力资源 Token，上报地址默认为 `https://nbdataxai.com/monitor/api/v1/agent/samples`；`test` 模式直接将 JSONL 数据写入固定文件 `/opt/computedock-agent/test-samples.jsonl`，不需要地址和 Token，也不会发起 HTTP 请求。

如需将 Agent 安装到已有算力容器，参阅 [ComputeDock Agent 手动安装指南](./AGENT_MANUAL_INSTALL.md)。

CPU 核会自动排序、去重并合并连续区间，例如 `3,2,2,1,8,7` 会统一显示并传递为 `1-3,7-8`。

容器 GPU 分配优先从 Docker `DeviceRequests` 读取，并兼容旧版 `NVIDIA_VISIBLE_DEVICES` 配置。GPU UUID 会尽可能映射为编号；只指定数量或无法识别具体设备时，冲突检查会按潜在重叠处理。

执行前脚本会：

- 校验 GPU/CPU、端口、数据根目录、容器名和本地镜像；
- 再次检查所选 GPU/CPU 是否与运行中容器重叠；
- 显示包含明文密码和 Token 的完整命令，并在确认后创建容器；
- 检查容器是否保持运行，并等待 SSH 和 Agent 都进入健康状态；失败时显示 Supervisor 状态和容器日志，并保留容器供排查。

内存只需输入 GiB 数值，例如输入 `256` 会生成 `-m 256G`、`--memory-swap 256G`，并自动将 `--shm-size` 设置为内存的一半。SSH 宿主机端口可以直接回车接受推荐值，也可以输入配置范围内的其他可用端口。最终挂载目录固定为 `<数据根目录>/<容器名称>`；确认创建后，目录不存在时脚本会申请 `sudo` 权限，创建目录并将 owner 修改为 `1001:1001`；目录已存在时直接复用，不申请 `sudo`，也不修改现有 owner。该 UID/GID 是新建宿主机挂载目录与容器交互用户之间的固定契约，不属于外部配置；容器启动时会校验交互用户的实际 UID/GID，不匹配则拒绝启动。

密码和 Agent Token 采用明文输入，并会出现在配置摘要和命令预览中。脚本执行时仍通过临时环境变量传入 Docker；容器管理员也可从容器配置中查看 `NEW_PWD` 和 `COMPUTEDOCK_TOKEN`。

也可以参考以下命令手动创建：

```shell
docker run -itd \
    --gpus '"device=0,1"' \
    --cpuset-cpus '0-15' \
    -m 256G \
    --memory-swap 256G \
    --shm-size=128G \
    --ulimit memlock=-1:-1 \
    -p 52236:22 \
    -e NEW_USER="hongbin" \
    -e NEW_PWD="hongbinpwd" \
    -e COMPUTEDOCK_SERVER_URL="https://monitor.example.com/api/v1/gpu/samples" \
    -e COMPUTEDOCK_CONTAINER_NAME="hongbin" \
    -e COMPUTEDOCK_INTERVAL="15" \
    -e COMPUTEDOCK_TOKEN="resource-token" \
    -e COMPUTEDOCK_STATE_DIR="/var/lib/computedock-agent" \
    -v /data/hongbin:/home/hongbin \
    --name hongbin \
    dilab-base:cuda-12.8-v5
```

容器内的 Supervisor 会在 Agent 异常退出后等待 5 秒并持续重启。配置错误不会无限重启；Agent、SSH 或实际 Agent 子进程缺失时，Docker 健康状态会变为 `unhealthy`。镜像不设置 Docker 自动重启策略，Supervisor 或整个容器退出后需要管理员自行恢复。

Agent 配置来自容器创建时的环境变量，修改上报地址、Token 或采集间隔需要重建容器。

### 在 Docker 镜像中使用 Agent 测试模式

将 `COMPUTEDOCK_TEST_OUTPUT` 设置为任意非空值后，容器服务脚本会使用 `--test-output /opt/computedock-agent/test-samples.jsonl` 启动 Agent。该变量仅作为 Docker 启动开关，不属于 Python Agent 的默认配置。测试模式无需设置 `COMPUTEDOCK_SERVER_URL` 和 `COMPUTEDOCK_TOKEN`：

```shell
docker run -itd \
    --gpus '"device=0"' \
    -p 52236:22 \
    -e NEW_USER="hongbin" \
    -e NEW_PWD="hongbinpwd" \
    -e COMPUTEDOCK_CONTAINER_NAME="agent-test-01" \
    -e COMPUTEDOCK_INTERVAL="15" \
    -e COMPUTEDOCK_TEST_OUTPUT="1" \
    --name agent-test-01 \
    dilab-base:cuda-12.8-v5
```

查看持续追加的测试数据：

```shell
docker exec agent-test-01 \
    tail -f /opt/computedock-agent/test-samples.jsonl
```

测试文件默认位于容器可写层，容器重启后仍然存在，删除容器时会一并删除。如需在删除容器前保留数据，可使用 `docker cp` 导出该文件。

## 开发测试

在项目根目录执行 Docker 集成测试：

```shell
python -m unittest discover -s tests -v
```

Agent 包测试仍在 `agent/` 目录内执行，具体命令见 `agent/README.md`。

# 潜在问题

构建的容器在执行systemctl daemon-reload之后会出现显卡丢失的问题

```
(container) $ nvidia-smi -L
Failed to initialize NVML: Unknown Error
```

这是一个已知的问题，据称将在[nvidia-container-toolkit v1.18.0](https://github.com/NVIDIA/nvidia-container-toolkit/issues/1227)版本解决，目前可考虑[临时解决方案](https://github.com/NVIDIA/nvidia-container-toolkit/discussions/1133)。

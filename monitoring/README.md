# ComputeDock 算力监控应用

该目录是独立的 GPU 监控应用：Agent 使用算力资源 Token 向 FastAPI 上报数据，管理员通过 React 页面管理资源、移除容器并查看 GPU 显存与利用率趋势。

## 快速启动

1. 检查项目中已经生成的本地配置，需要时修改管理员账号、密码或监听配置：

   ```shell
   cd monitoring
   chmod 600 .env
   $EDITOR .env
   ```

2. 启动数据库和应用：

   ```shell
   docker compose up --build -d
   docker compose ps
   curl http://127.0.0.1:8000/api/health
   ```

3. 浏览器访问 `http://127.0.0.1:8000`，使用 `.env` 中的管理员账号登录。首次启动环境变量只负责创建管理员，后续密码以数据库为准。

应用容器只监听 HTTP。正式部署时由外部 Nginx 终止 HTTPS，并将请求代理到 `monitoring` 的 8000 端口。生产环境应设置 `COOKIE_SECURE=true`。应用通过 `X-Forwarded-Prefix` 动态支持任意单级或多级子路径，无需重新构建镜像或在代码中写死部署路径：

```nginx
location = /monitor {
    return 301 /monitor/;
}

location /monitor/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Prefix /monitor;
}
```

`proxy_pass` 末尾的 `/` 不能省略：它负责在转发时移除外部前缀。应用会根据请求头生成静态资源、管理 API、前端路由和 Cookie 路径。直接访问 `http://127.0.0.1:8000/` 时没有该请求头，应用仍按根路径运行。

## Agent 上报

在概览页创建算力资源后复制完整 Token，再把完整接口路径传给现有 Agent：

```shell
computedock-agent run \
  --server-url 'https://monitor.example.com/monitor/api/v1/agent/samples' \
  --container-name 'worker-01' \
  --interval 15 \
  --token 'cdr_xxx'
```

同一资源中的 GPU UUID 会去重计算已分配卡数；多个容器共用同一 UUID 时，各容器的历史曲线仍各自独立。容器超过 120 秒没有成功请求会显示失联，但仍计入分配，直到管理员人工移除。

## 生成模拟数据

先创建资源并复制 Token，再运行：

```shell
python scripts/mock_data.py \
  --token 'cdr_xxx' \
  --containers 3 \
  --gpus-per-container 2 \
  --hours 2 \
  --interval 60 \
  --shared-gpu
```

脚本经过正式 Agent 接口写入最近 24 小时内的数据，包含真实零值、数据缺口和可选共享 GPU。服务端拒绝超过 24 小时的补传，因此该脚本也将 `--hours` 限制为 24；7 日视图会正确显示其余时段为无数据。

如需验证登录、幂等、共享 GPU、容器移除/重建以及资源删除后的 Token 失效，可对测试环境运行：

```shell
backend/.venv/bin/python scripts/smoke_test.py --password 'change-me-admin'
```

## 本地开发与测试

后端：

```shell
cd backend
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check src tests
```

前端：

```shell
cd frontend
npm install
npm test
npm run build
```

运行中的 Compose 环境可执行端到端测试：

```shell
cd frontend
MONITORING_E2E_PASSWORD='change-me-admin' npx playwright install chromium
MONITORING_E2E_PASSWORD='change-me-admin' npm run test:e2e
```

## 存储与保留

`sample_batches` 和 `gpu_samples` 都按 `collected_at` 使用 PostgreSQL 原生日分区。数据库镜像安装 `pg_partman`，后台 worker 每小时提前维护分区并直接删除超过 30 天的整日分区。删除算力资源或移除容器不会提前删除历史行。当前设计只保留原始样本，不生成额外聚合表；按规划规模建议为数据库卷预留至少 50 GB。

Compose 使用 PostgreSQL 18 推荐的 `/var/lib/postgresql` 卷挂载方式。若从早期 PostgreSQL 主版本升级，不能直接复用旧数据目录，必须先备份并按 PostgreSQL 官方升级流程迁移。

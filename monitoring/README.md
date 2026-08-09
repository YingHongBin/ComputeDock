# ComputeDock 算力监控应用

该目录包含四个服务：`collector` 接收 Agent 数据，`app` 提供管理 API 和 React 页面，`worker` 负责邮件、到期任务和历史聚合，`database` 保存 PostgreSQL 数据。采集与管理服务独立部署，更新管理页面不会中断 Agent 上报。

## 快速启动

1. 从示例复制本地配置并填写数据库、初始管理员、公开访问地址和 SMTP：

   ```shell
   cd monitoring
   cp .env.exmaple .env
   chmod 600 .env
   $EDITOR .env
   ```

   `ADMIN_USERNAME`、`ADMIN_PASSWORD` 和 `ADMIN_EMAIL` 只用于首次创建管理员。后续账号资料和密码以数据库为准。邮件验证链接会基于 `PUBLIC_BASE_URL` 生成，生产环境必须设为用户实际访问的 HTTPS 地址。

2. 启动全部服务：

   ```shell
   docker compose up --build -d
   docker compose ps
   curl http://127.0.0.1:8000/api/health
   curl http://127.0.0.1:8001/api/health
   ```

3. 浏览器访问 `http://127.0.0.1:8000`。普通用户完成邮箱验证后还需管理员审核，审核通过才能登录。

若未配置 SMTP，业务数据仍会保存，但邮件会留在待重试队列中；注册验证、密码重置和通知邮件将无法送达。

## 用户、项目与算力申请

- 普通用户可以查看当前算力资源和容器使用情况、提交算力申请，并对自己已通过且未到期的申请提交延时、扩容或释放部分 GPU 的变更申请。
- 管理员与普通用户使用相同的申请规则，也可以审批自己的申请。只有管理员能审核注册和算力申请、管理用户/项目、创建或编辑资源、禁用资源、移除容器及查看历史面板。
- 创建项目时，创建者不会自动成为项目成员；申请人必须已加入目标项目。
- 初始使用天数和单次延时均为 1–14 天的正整数。GPU 数量只校验不超过资源总卡数，不做并发预留或总申请量限制。
- 申请从首个容器首次成功上报开始计时。到期前一天显示提醒标签并向申请人发邮件，同时抄送所有有效管理员；到期后继续接收该 Token 的上报。
- 禁用用户、项目或资源只会自动拒绝仍在申请中的请求和变更，不影响已经通过的申请或 Token。资源“删除”统一采用禁用语义，并可重新启用。

普通用户不能查看或复制任何 Token。管理员可重复复制已通过申请的 Token；Token 明文保存、不支持重置，也不记录复制行为。新建资源不再创建资源级 Token，升级前已有资源 Token 继续有效。

## Agent 上报

管理员审核算力申请后，在“算力申请”页复制该申请的 Token，再传给 Agent：

```shell
computedock-agent run \
  --server-url 'https://monitor.example.com/monitor/api/v1/agent/samples' \
  --container-name 'worker-01' \
  --interval 15 \
  --token 'cda_xxx'
```

同一申请中的 GPU UUID 会去重计算实际使用卡数；超过申请卡数时只提示超额，不拒绝数据。多个容器使用同一 UUID 时，各容器曲线仍然独立。容器超过 120 秒没有成功请求会显示失联，但仍计入实际使用，直到管理员移除。移除后同名容器再次上报会创建新的容器代次。

升级前已存在、无法关联到真实用户和项目的容器会完整保留，不伪造归属，也不支持事后修改归属；只有仍在运行的未归属容器会出现在当前资源详情中。

## 反向代理

管理页面使用宿主机 8000 端口，collector 使用 8001 端口。正式部署时由外部 Nginx 终止 HTTPS，将上报地址精确转发到 collector，其余请求转发到 app。生产环境应设置 `COOKIE_SECURE=true`。

```nginx
location = /monitor {
    return 301 /monitor/;
}

location = /monitor/api/v1/agent/samples {
    proxy_pass http://127.0.0.1:8001/api/v1/agent/samples;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Prefix /monitor;
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

通用 app location 中 `proxy_pass` 末尾的 `/` 负责移除外部前缀，不能省略。应用会根据 `X-Forwarded-Prefix` 生成静态资源、管理 API、前端路由和 Cookie 路径。

## 升级顺序与数据兼容

数据库迁移由 collector 启动时执行。涉及本次数据结构和采集令牌升级时，先更新 collector，确认健康后再更新 app 和 worker：

```shell
docker compose build collector app worker
docker compose up -d --no-deps collector
docker compose up -d --no-deps app worker
```

只更新管理 API 和页面时可单独重建 app：

```shell
docker compose build app
docker compose up -d --no-deps app
```

迁移保留现有容器、原始样本、聚合结果和旧资源 Token。历史数据计入“历史未归属”，但不提供单独入口和归属修改功能。

## 存储与历史展示

`sample_batches` 和 `gpu_samples` 按 `collected_at` 使用 PostgreSQL 原生日分区。`pg_partman` 删除超过 30 天的原始秒级分区；项目、用户、申请、容器和小时聚合不删除。

worker 按 `BUSINESS_TIMEZONE` 每天聚合昨天的数据，首次启动会从现存最早原始样本补齐到昨天，聚合结果按小时永久保存，不考虑迟到补传。运行中容器的近 1 天/近 7 天趋势仍读取原始数据；已移除容器的完整生命周期趋势读取小时聚合数据，不提供明细、日期筛选或导出。

用户历史和项目历史面板只展示历史算力申请、历史容器记录和容器下的使用趋势，不统计卡天。

## 生成模拟数据

先创建资源、项目和算力申请，审批后复制申请 Token，再运行：

```shell
python scripts/mock_data.py \
  --token 'cda_xxx' \
  --containers 3 \
  --gpus-per-container 2 \
  --hours 2 \
  --interval 60 \
  --shared-gpu
```

脚本通过正式 Agent 接口写入最近 24 小时的数据。服务端拒绝超过 24 小时的样本，因此脚本也将 `--hours` 限制为 24。

运行中的 Compose 环境可执行完整申请、审批、采集、容器代次和资源禁用冒烟流程：

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
npm test -- --run
npm run build
```

运行中的 Compose 环境可执行端到端测试：

```shell
cd frontend
MONITORING_E2E_PASSWORD='change-me-admin' npx playwright install chromium
MONITORING_E2E_PASSWORD='change-me-admin' npm run test:e2e
```

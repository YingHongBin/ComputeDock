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

   `ADMIN_USERNAME`、`ADMIN_PASSWORD`、`ADMIN_FULL_NAME` 和 `ADMIN_EMAIL` 均为必填项，只用于首次创建管理员。初始管理员邮箱会直接标记为已验证；后续账号资料和密码以数据库为准。设置页中的 `API Base URL` 决定邮件验证、密码重置和邮箱变更链接的基础地址；尚未保存数据库配置时回退到 `PUBLIC_BASE_URL`。

2. 启动全部服务：

   ```shell
   docker compose up --build -d
   docker compose ps
   curl http://127.0.0.1:8000/api/health
   curl http://127.0.0.1:8001/api/health
   ```

3. 浏览器访问 `http://127.0.0.1:8000`。普通用户完成邮箱验证后还需管理员审核，审核通过才能登录。

若未配置 SMTP，业务数据仍会保存，但邮件会留在待重试队列中；注册验证、密码重置和通知邮件将无法送达。

管理员可在“设置”页维护 SMTP Host、端口、用户名、密码、发件邮箱、发件人名称和 TLS，并向当前管理员绑定邮箱发送测试邮件。数据库中保存过配置后将优先于 `.env`，Worker 会在下一次轮询时自动读取，无需重启；SMTP 密码不会通过 API 或页面回传。启用 TLS 时，465 端口使用隐式 TLS，其他端口使用 STARTTLS。

## 用户、Squad与算力申请

- 普通用户可以查看当前算力资源和容器使用情况、提交算力申请，并对自己已通过且未到期的申请提交延时、扩容、释放部分 GPU 或独立调整 CPU/内存的变更申请。
- 管理员与普通用户使用相同的申请规则，也可以审批自己的申请。只有管理员能审核注册和算力申请、管理用户/Squad、创建或编辑资源、禁用资源、移除容器及查看历史面板。
- 所有有效用户都能查看并申请所有启用中的Squad；禁用的Squad只在管理员管理页显示，且不能用于新申请。
- 初始使用天数和单次延时均为 1–14 天的正整数。GPU、CPU、内存只校验单笔不超过服务器总容量，不限制累计申请量；获批额度会参与剩余额度展示。
- 申请从首个容器首次成功上报开始计时。到期前一天显示提醒标签并向申请人发邮件，同时抄送所有有效管理员；到期后继续接收该 Token 的上报。
- 禁用用户、Squad或资源只会自动拒绝仍在申请中的请求和变更，已经通过的申请和 Token 仍可供已有容器上报，但新建或重建容器会检查用户、Squad 和服务器是否启用。资源“删除”统一采用禁用语义，并可重新启用。

普通用户不能查看或复制任何 Token。管理员可重复复制已通过申请的 Token；Token 明文保存、不支持重置，也不记录复制行为。算力资源不创建资源级 Token，Agent 只能使用已通过申请的 Token。

## Agent 上报

管理员审核算力申请后，在“算力申请”页复制该申请的 Token，再传给 Agent：

```shell
computedock-agent run \
  --server-url 'https://monitor.example.com/monitor/api/v1/agent/samples' \
  --container-name 'worker-01' \
  --interval 15 \
  --token 'cda_xxx'
```

同一申请中的 GPU UUID 会去重计算实际使用卡数；超过申请卡数时只提示超额，不拒绝数据。不同申请的容器使用同一 UUID 时，各容器曲线仍然独立；同一申请不能同时关联多个未移除容器。容器超过 120 秒没有成功请求会显示失联，但仍计入实际使用，直到管理员移除。移除后同名容器再次上报会创建新的容器代次。

所有容器必须绑定算力申请。页面主要显示Squad名称和申请人姓名，Agent 上传的容器名称作为同一申请内的内部实例标识展示。

## 反向代理

管理页面使用宿主机 8000 端口，collector 使用 8001 端口。正式部署时由外部 Nginx 终止 HTTPS，将 `/api/v1/agent/` 下的上报及额度查询请求转发到 collector，其余请求转发到 app。生产环境应设置 `COOKIE_SECURE=true`。

```nginx
location = /monitor {
    return 301 /monitor/;
}

location /monitor/api/v1/agent/ {
    proxy_pass http://127.0.0.1:8001/api/v1/agent/;
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

## 全新部署与独立服务更新

app、collector 和 worker 使用独立构建目标、镜像和版本标签，运行时都只依赖 database，可以分别更新。`APP_IMAGE_TAG`、`COLLECTOR_IMAGE_TAG` 和 `WORKER_IMAGE_TAG` 可单独指定；未指定时均回退到 `MONITORING_IMAGE_TAG`。

当前版本采用全新数据库 Schema，不支持从旧版数据库原地升级。部署当前版本前需要由运维人员显式删除旧数据库卷并创建空数据库；应用本身不会自动删除数据：

```shell
docker compose down
docker volume ls
# 确认实际数据库卷名称后，再显式删除该卷
docker volume rm <database-volume-name>
docker compose up --build -d
```

数据库迁移由 app 在启动管理服务前执行，collector 和 worker 不执行 Alembic。全新数据库只执行单一的 `0001_initial`。完成首次部署后，app、collector 和 worker仍可使用独立镜像标签分别更新：

```shell
docker compose build app
docker compose up -d --no-deps --force-recreate app
docker compose ps app
docker compose logs --tail=100 app
docker compose build collector
docker compose up -d --no-deps --force-recreate collector
docker compose build worker
docker compose up -d --no-deps --force-recreate worker
```

不涉及数据库结构时，只需构建并重建发生变化的服务。更新 app 不会中断 Agent 上报，更新 collector 也不会重启 app 或 worker：

```shell
docker compose build app
docker compose up -d --no-deps app
```

需要只执行数据库迁移而不常驻启动管理服务时，复用 app 镜像：

```shell
docker compose run --rm --no-deps app alembic upgrade head
```

仅新增数据库迁移文件时，collector 和 worker 均无需重新构建；迁移文件只随 app 镜像发布。

## 存储与历史展示

`sample_batches` 和 `gpu_samples` 按 `collected_at` 使用 PostgreSQL 原生日分区。`pg_partman` 删除超过 30 天的原始秒级分区；Squad、用户、申请、容器和小时聚合不删除。

worker 按 `BUSINESS_TIMEZONE` 每天 08:00 聚合昨天的数据，聚合结果按小时永久保存，不考虑迟到补传。运行中容器趋势读取原始数据；已移除容器的完整生命周期趋势读取小时聚合数据，不提供明细、日期筛选或导出。

用户历史和Squad历史面板只展示历史算力申请、历史容器记录和容器下的使用趋势，不统计卡天。

## 生成模拟数据

先创建资源、Squad和算力申请，审批后复制申请 Token，再运行：

```shell
python scripts/mock_data.py \
  --token 'cda_xxx' \
  --containers 1 \
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

## CPU、内存与申请额度

新建/编辑服务器时必须填写 CPU 逻辑核心数、内存总容量（GiB），以及 CPU、内存的单次申请默认值。所有值为正整数，默认值不能超过服务器总容量。选择服务器后，申请表自动填入这两个默认值，允许申请人修改；GPU 数量和使用天数仍由申请人填写。

提交和审批只检查单笔 GPU、CPU、内存申请是否超过服务器总容量。弹窗中的申请剩余额度按“总容量减去已批准且未到期的申请额度”计算，包含尚未启动的获批申请；待审批、已拒绝、已到期申请不占用额度。超过剩余额度时提示但允许提交，超配时显示剩余 0 及超配数量。资源卡上的 GPU 实际分配量仍来自容器上报，与审批额度分开统计。

CPU 和内存可独立申请调整，输入调整后的总量，审批通过后才更新额度。API 的变更类型 `cpu`、`memory` 使用 `amount` 表示目标总量；`expand`、`release`、`extend` 继续表示 GPU 或天数增减量。尚未启动的申请也可调整 CPU、内存。已有运行容器的限制由管理员同步调整，系统不会自动执行 Docker 更新。

`GET /api/v1/agent/allocation` 使用申请 Token 的 `Authorization: Bearer ...` 认证，返回申请 ID、服务器名称、GPU 型号及获批的 GPU/CPU/内存容量。查询不启动使用期限；无效 Token、已到期申请、已禁用关联对象或仍有未移除容器的申请不能用于创建。此接口由 collector 提供，反向代理需要按上面的 `/api/v1/agent/` 路径转发。

一份申请只允许关联一个未移除容器，停止或失联不视为删除。重建前需删除宿主机旧容器，并在监控页面移除旧容器记录；重建沿用原申请期限。首次成功上报仍是申请开始计时的时点。

本次直接更新全新部署使用的 `0001_initial` 数据库定义，不提供历史数据库迁移、补录或默认值回填；已有数据库不能仅通过重复执行 `alembic upgrade head` 获得这些新增字段。

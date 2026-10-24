# AI 服务后端

一个生产级风格的 AI 服务后端骨架：用户、会话、消息的 CRUD，加上异步任务（会话统计 / 导出）、限流与幂等。FastAPI + PostgreSQL + Redis + RabbitMQ(Celery)，Docker Compose 一键启动。

## 技术栈

| 层 | 选型 |
|---|---|
| Web 框架 | FastAPI + Pydantic v2 |
| ORM / 迁移 | SQLAlchemy 2.0（异步 asyncpg + 同步 psycopg 共用模型）+ Alembic |
| 数据库 | PostgreSQL 16（JSONB、UUID、CHECK 约束枚举、软删除、部分索引） |
| 缓存 | Redis 7（任务状态读缓存、限流、幂等） |
| 异步任务 | Celery 5 + RabbitMQ 3（DLX 死信、Beat 周期任务、显式重试） |
| 日志 | structlog JSON + request_id 中间件 |
| 测试 | pytest + httpx ASGI + Celery eager 模式 |
| CI | GitHub Actions（ruff lint + format + pytest） |

## 快速开始

```bash
# 一条命令启动全部服务（PostgreSQL / Redis / RabbitMQ / 迁移 / API / Worker / Beat）
docker compose up --build
```

启动后：

- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health/ready
- RabbitMQ 管理台：http://localhost:15672（app / app）

停止并清理：

```bash
docker compose down -v
```

## 运行测试

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

测试会自动创建独立数据库 `app_test` 并跑迁移，用 Celery eager 模式同步执行任务，不需要启动 Worker。

## 核心设计

### 数据库

- **枚举用 VARCHAR + CHECK 约束**而非 PostgreSQL 原生 ENUM，避免 Alembic 迁移时增删枚举值的额外 DDL 成本。
- **软删除**：`chat_sessions.deleted_at`，查询默认过滤；由 Beat 周期任务物理清理超过 30 天的软删除记录。
- **任务状态机**：`pending → running → succeeded / failed`，`claim` 用条件更新（`UPDATE ... WHERE status = 'pending'`）保证重复投递的消息不会重复执行。
- **命名约束**：所有约束显式命名，Alembic autogenerate 才能稳定对比。

### 异步任务

- PostgreSQL 是任务状态的**唯一事实来源**，Redis 只做读加速（缓存丢了不丢状态）。
- `acks_late` + `reject_on_worker_lost`：Worker 崩溃时消息重回队列。
- 失败消息**仍 ack**：重试由业务状态机显式重投（`mark_retry` 置回 pending + `self.retry` 重发），避免 attempts 用尽的任务无限回队形成毒消息循环。
- **死信交换机** `ai.dlx`：被显式拒绝的消息落到 `ai.dead` 队列供排查。
- **补偿扫描**：Beat 每 120s 扫描 `pending > 300s` / `running > 600s` 且 attempts < 3 的任务并重投。

### 错误处理

- 所有错误统一信封：`{ "error": { "code", "message", "details", "request_id" } }`。
- 全局 `request_id` 中间件，客户端可通过 `X-Request-Id` 传入追踪。
- 自定义异常类（`NotFoundError` / `ConflictError` / `RateLimitedError` 等）映射到对应 HTTP 状态码。

### 限流与幂等

- **固定窗口限流**：Lua 脚本把 `INCR + EXPIRE` 做成原子操作；已认证接口按用户、注册接口按 IP。Redis 故障时降级放行。
- 响应头 `X-RateLimit-Limit / Remaining / Reset`，超限返回 429 + `Retry-After`。
- **幂等**：`POST /v1/tasks` 支持 `Idempotency-Key` 请求头，相同 key 在 TTL 内返回同一任务结果，防止客户端因超时重复提交。

## 项目结构

```
app/
├── api/v1/          # 路由：health / users / sessions / tasks
├── clients/         # Redis、限流、幂等、任务缓存
├── core/            # 配置、错误、日志、中间件、安全
├── db/              # 异步 + 同步引擎
├── models/          # ORM 模型
├── repositories/    # 数据访问层（API 异步 / Worker 同步共用语句）
├── schemas/         # Pydantic 模型
└── workers/         # Celery 应用、任务处理器、分发
alembic/             # 数据库迁移
docker/              # Dockerfile
tests/               # pytest 测试
```

## 一条命令验证

```bash
# 启动
docker compose up --build
# 健康
curl http://localhost:8000/health/ready
# 测试
pytest tests/ -v
```

## 国内镜像加速

Dockerfile 默认使用阿里云 PyPI 镜像。若拉取基础镜像慢，可配置 Docker 镜像加速器或提前拉取：

```bash
docker pull docker.m.daocloud.io/library/postgres:16-alpine
docker tag docker.m.daocloud.io/library/postgres:16-alpine postgres:16-alpine
```

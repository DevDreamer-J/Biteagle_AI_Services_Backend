"""测试夹具：独立测试库 + Redis db1 + Celery eager 模式。

所有测试都跑在真实的 PostgreSQL/Redis 上（compose 暴露的端口），
但用独立的 database / db index，避免污染开发数据。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

# 在导入 app 之前锁定测试环境
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("POSTGRES_DB", "app_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")

import httpx
import psycopg
import pytest
from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import dispose_engine, dispose_sync_engine, get_session_factory
from app.main import app
from app.workers import tasks  # noqa: F401  注册任务到 celery_app
from app.workers.celery_app import celery_app

# 任务同步执行，不需要启动 worker；异常向上抛出，便于断言失败路径
celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_DB = "app_test"
_TABLES = ("tasks", "messages", "chat_sessions", "users")


def _admin_conn():
    """连到 postgres 默认库，用于创建/删除测试库。"""
    settings = get_settings()
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        dbname="postgres",
        autocommit=True,
    )


@pytest.fixture(scope="session")
def setup_test_database():
    """创建测试库并跑迁移，整个测试会话只做一次。"""
    conn = _admin_conn()
    try:
        # 断开可能残留的连接后重建库
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (TEST_DB,),
        )
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    finally:
        conn.close()

    # alembic 从 settings 读 URL，已经指向 app_test
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr}"

    yield

    # 释放 async engine 的连接池，否则 drop database 会因活跃连接失败
    asyncio.run(dispose_engine())
    dispose_sync_engine()

    conn = _admin_conn()
    try:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    finally:
        conn.close()


@pytest.fixture
async def db_session(setup_test_database):
    """每个测试前清空所有表 + Redis，保证用例隔离。"""
    # Redis 客户端是全局单例，绑定了创建时的事件循环；
    # pytest-asyncio 每个测试用新 loop，必须重置否则会 "Event loop is closed"
    import app.clients.redis as redis_mod
    import app.clients.task_cache as cache_mod

    redis_mod._client = None
    cache_mod._sync_client = None

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text(f"TRUNCATE TABLE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
        await session.commit()

    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    redis.flushdb()
    redis.close()

    yield

    # 每个测试后释放连接池（异步 + Celery worker 用的同步），
    # 避免 app_test 残留活跃连接导致 teardown drop 失败
    await dispose_engine()
    dispose_sync_engine()


@pytest.fixture
async def client(db_session) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI 测试客户端，跳过 lifespan（不连外部依赖的生命周期管理）。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def api_key(client) -> str:
    """注册一个用户并返回 api_key，方便需要认证的用例直接用。"""
    # 用同步方式在 fixture 里发请求比较别扭，改为提供 helper
    raise RuntimeError("用 register_user(client) 辅助函数替代")


async def register_user(
    client: httpx.AsyncClient, *, email: str, display_name: str = "Tester"
) -> dict:
    """注册用户，返回包含 api_key 的响应体。"""
    response = await client.post(
        "/v1/users",
        json={"email": email, "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def auth_headers(client: httpx.AsyncClient, *, email: str) -> dict[str, str]:
    user = await register_user(client, email=email)
    return {"X-API-Key": user["api_key"]}

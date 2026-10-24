"""任务状态读缓存。

PostgreSQL 仍是任务状态的唯一事实来源：缓存丢了只会多一次回源查询，
不会丢状态。写缓存在状态变更之后进行，TTL 到期自动过期。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import structlog
from redis import Redis

from app.clients.redis import get_redis
from app.core.config import get_settings
from app.models.task import Task

logger = structlog.get_logger(__name__)

TTL_SECONDS = 3600

_sync_client: Redis | None = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def task_state_payload(task: Task) -> dict[str, Any]:
    """把 ORM 对象压成缓存友好的 JSON 结构（字段与 TaskRead 对齐）。"""
    return {
        "id": str(task.id),
        "type": task.type.value,
        "status": task.status.value,
        "session_id": str(task.session_id) if task.session_id else None,
        "payload": task.payload or {},
        "result": task.result,
        "error": task.error,
        "attempts": task.attempts,
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
    }


def _key(task_id: uuid.UUID | str) -> str:
    return f"task:{task_id}"


def get_sync_redis() -> Redis:
    """Celery worker 用的同步客户端。"""
    global _sync_client
    if _sync_client is None:
        settings = get_settings()
        _sync_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_timeout,
            socket_timeout=settings.redis_timeout,
        )
    return _sync_client


async def get_task_state(task_id: uuid.UUID) -> dict[str, Any] | None:
    """缓存未命中或 Redis 异常都返回 None，由调用方回源数据库。"""
    try:
        raw = await get_redis().get(_key(task_id))
    except Exception as exc:
        logger.warning("task_cache_get_failed", task_id=str(task_id), error=str(exc))
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("task_cache_corrupted", task_id=str(task_id))
        return None


async def set_task_state(state: dict[str, Any]) -> None:
    try:
        await get_redis().set(_key(state["id"]), json.dumps(state), ex=TTL_SECONDS)
    except Exception as exc:
        logger.warning("task_cache_set_failed", task_id=state.get("id"), error=str(exc))


def set_task_state_sync(state: dict[str, Any]) -> None:
    try:
        get_sync_redis().set(_key(state["id"]), json.dumps(state), ex=TTL_SECONDS)
    except Exception as exc:
        logger.warning("task_cache_set_failed", task_id=state.get("id"), error=str(exc))


async def close_task_cache() -> None:
    global _sync_client
    if _sync_client is not None:
        _sync_client.close()
    _sync_client = None

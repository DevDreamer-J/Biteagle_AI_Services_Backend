"""幂等键缓存：相同 key 在 TTL 内直接返回上次结果。

用于任务提交等写操作，防止客户端因网络超时重复提交产生多条任务。
"""

from __future__ import annotations

import json

import structlog

from app.clients.redis import get_redis
from app.core.config import get_settings

logger = structlog.get_logger(__name__)


def _key(namespace: str, idempotency_key: str) -> str:
    return f"idem:{namespace}:{idempotency_key}"


async def get_idempotent(namespace: str, idempotency_key: str) -> dict | None:
    try:
        raw = await get_redis().get(_key(namespace, idempotency_key))
    except Exception as exc:
        logger.warning("idempotency_get_failed", key=idempotency_key, error=str(exc))
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def set_idempotent(namespace: str, idempotency_key: str, payload: dict) -> None:
    settings = get_settings()
    try:
        await get_redis().set(
            _key(namespace, idempotency_key),
            json.dumps(payload),
            ex=settings.idempotency_ttl_seconds,
        )
    except Exception as exc:
        logger.warning("idempotency_set_failed", key=idempotency_key, error=str(exc))

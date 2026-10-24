"""Redis 客户端（异步）。"""

import structlog
from redis.asyncio import Redis

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        settings = get_settings()
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_timeout,
            socket_timeout=settings.redis_timeout,
        )
    return _client


async def check_redis() -> bool:
    try:
        await get_redis().ping()
        return True
    except Exception as exc:
        logger.warning("redis_check_failed", error=str(exc))
        return False


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None

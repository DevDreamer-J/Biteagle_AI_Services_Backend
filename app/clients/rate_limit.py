"""基于 Redis 的固定窗口限流。

用 Lua 脚本把 INCR + EXPIRE 做成原子操作，避免并发下窗口被反复续期。
Redis 不可用时降级为放行，只打告警，保证业务不因缓存故障雪崩。
"""

from __future__ import annotations

import structlog

from app.clients.redis import get_redis
from app.core.config import get_settings

logger = structlog.get_logger(__name__)

_LUA_SCRIPT = """
local current = redis.call('incr', KEYS[1])
if current == 1 then
    redis.call('expire', KEYS[1], ARGV[1])
end
local ttl = redis.call('ttl', KEYS[1])
return {current, ttl}
"""


async def check_rate_limit(
    key: str, *, limit: int | None = None, window_seconds: int | None = None
) -> tuple[bool, int, int]:
    """返回 (是否放行, 当前窗口剩余次数, 重置秒数)。"""
    settings = get_settings()
    limit = limit if limit is not None else settings.rate_limit_per_minute
    window = window_seconds if window_seconds is not None else settings.rate_limit_window_seconds

    try:
        current, ttl = await get_redis().eval(_LUA_SCRIPT, 1, key, window)
        current = int(current)
        ttl = int(ttl)
        reset_in = ttl if ttl >= 0 else window
        allowed = current <= limit
        remaining = max(limit - current, 0)
        return allowed, remaining, reset_in
    except Exception as exc:
        logger.warning("rate_limit_redis_failed", key=key, error=str(exc))
        # Redis 故障时放行，避免缓存层拖垮写接口
        return True, limit, window

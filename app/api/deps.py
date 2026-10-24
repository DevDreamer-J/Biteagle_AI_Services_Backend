"""公共依赖：数据库会话、API Key 认证、限流。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.rate_limit import check_rate_limit
from app.core.config import get_settings
from app.core.errors import RateLimitedError, UnauthorizedError
from app.core.security import hash_api_key
from app.db.session import get_session
from app.models.user import User
from app.repositories.user_repo import UserRepository

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> User:
    if not x_api_key:
        raise UnauthorizedError("缺少 X-API-Key 请求头")

    user = await UserRepository(session).get_by_api_key_hash(hash_api_key(x_api_key))
    if user is None or not user.is_active:
        raise UnauthorizedError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def rate_limit_by_user(user: CurrentUser, response: Response) -> None:
    """已认证接口按用户维度限流。"""
    settings = get_settings()
    allowed, remaining, reset_in = await check_rate_limit(f"u:{user.id}")
    response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_per_minute)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_in)
    if not allowed:
        raise RateLimitedError(
            details={"limit": settings.rate_limit_per_minute, "reset_in": reset_in},
            headers={"Retry-After": str(reset_in)},
        )


async def rate_limit_by_ip(request: Request, response: Response) -> None:
    """未认证接口（如注册）按客户端 IP 限流。"""
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    allowed, remaining, reset_in = await check_rate_limit(f"ip:{client_ip}")
    response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_per_minute)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_in)
    if not allowed:
        raise RateLimitedError(
            details={"limit": settings.rate_limit_per_minute, "reset_in": reset_in},
            headers={"Retry-After": str(reset_in)},
        )


RateLimitedByUser = Annotated[None, Depends(rate_limit_by_user)]
RateLimitedByIP = Annotated[None, Depends(rate_limit_by_ip)]

"""仓储层基类：只做数据访问，事务边界由调用方（服务/接口）控制。"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, obj: T) -> T:
        """加入会话并 flush 以获得数据库生成的默认值（不提交事务）。"""
        self.session.add(obj)
        await self.session.flush()
        return obj

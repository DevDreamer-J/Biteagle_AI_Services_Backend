"""会话数据访问。默认过滤软删除记录。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.models.chat_session import ChatSession
from app.repositories.base import BaseRepository


class SessionRepository(BaseRepository):
    async def create(self, *, user_id: uuid.UUID, title: str = "") -> ChatSession:
        return await self.add(ChatSession(user_id=user_id, title=title))

    async def get(
        self, session_id: uuid.UUID, *, include_deleted: bool = False
    ) -> ChatSession | None:
        stmt = select(ChatSession).where(ChatSession.id == session_id)
        if not include_deleted:
            stmt = stmt.where(ChatSession.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> Sequence[ChatSession]:
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id, ChatSession.deleted_at.is_(None))
            .order_by(ChatSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ChatSession)
            .where(ChatSession.user_id == user_id, ChatSession.deleted_at.is_(None))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def update_title(self, chat_session: ChatSession, title: str) -> ChatSession:
        chat_session.title = title
        await self.session.flush()
        return chat_session

    async def touch_last_message(
        self, chat_session: ChatSession, *, at: datetime | None = None
    ) -> ChatSession:
        chat_session.last_message_at = at or datetime.now(UTC)
        await self.session.flush()
        return chat_session

    async def soft_delete(self, chat_session: ChatSession) -> None:
        chat_session.deleted_at = datetime.now(UTC)
        await self.session.flush()

    async def purge_expired(self, *, inactive_days: int = 30) -> int:
        """物理删除软删除超过 N 天的会话（由 Celery Beat 调用），返回删除行数。"""
        cutoff = datetime.now(UTC) - timedelta(days=inactive_days)
        stmt = delete(ChatSession).where(
            ChatSession.deleted_at.is_not(None), ChatSession.deleted_at < cutoff
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

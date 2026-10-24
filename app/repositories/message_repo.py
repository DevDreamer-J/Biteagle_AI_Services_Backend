"""消息数据访问。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.enums import MessageRole
from app.models.message import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository):
    async def create(self, *, session_id: uuid.UUID, role: MessageRole, content: str) -> Message:
        return await self.add(Message(session_id=session_id, role=role, content=content))

    async def get(self, message_id: uuid.UUID) -> Message | None:
        return await self.session.get(Message, message_id)

    async def list_by_session(
        self,
        session_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
        ascending: bool = True,
    ) -> Sequence[Message]:
        order = Message.created_at.asc() if ascending else Message.created_at.desc()
        stmt = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(order)
            .limit(limit)
            .offset(offset)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def count_by_session(self, session_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Message).where(Message.session_id == session_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_by_role(self, session_id: uuid.UUID) -> dict[str, int]:
        stmt = (
            select(Message.role, func.count())
            .where(Message.session_id == session_id)
            .group_by(Message.role)
        )
        rows = (await self.session.execute(stmt)).all()
        return {str(role.value): int(count) for role, count in rows}

"""用户数据访问。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_api_key_hash(self, api_key_hash: str) -> User | None:
        stmt = select(User).where(User.api_key_hash == api_key_hash)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, *, email: str, display_name: str, api_key_hash: str) -> User:
        return await self.add(
            User(email=email, display_name=display_name, api_key_hash=api_key_hash)
        )

    async def list(self, *, limit: int = 20, offset: int = 0) -> Sequence[User]:
        stmt = select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
        return (await self.session.execute(stmt)).scalars().all()

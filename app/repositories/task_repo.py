"""任务数据访问（异步，API 侧）。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.enums import TaskStatus, TaskType
from app.models.task import Task
from app.repositories.base import BaseRepository
from app.repositories.task_statements import (
    claim_stmt,
    failed_stmt,
    retry_stmt,
    succeeded_stmt,
)


class TaskRepository(BaseRepository):
    async def create(
        self,
        *,
        user_id: uuid.UUID,
        type: TaskType,
        payload: dict | None = None,
        session_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> Task:
        task = Task(
            user_id=user_id,
            session_id=session_id,
            type=type,
            payload=payload or {},
        )
        if task_id is not None:
            # 让 Celery 的 task_id 与业务主键一致，便于双向追踪
            task.id = task_id
        return await self.add(task)

    async def get(self, task_id: uuid.UUID) -> Task | None:
        return await self.session.get(Task, task_id)

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: TaskStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[Task]:
        stmt = select(Task).where(Task.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        stmt = stmt.order_by(Task.created_at.desc()).limit(limit).offset(offset)
        return (await self.session.execute(stmt)).scalars().all()

    async def count_for_user(self, user_id: uuid.UUID, *, status: TaskStatus | None = None) -> int:
        stmt = select(func.count()).select_from(Task).where(Task.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        return int((await self.session.execute(stmt)).scalar_one())

    async def claim(self, task_id: uuid.UUID) -> bool:
        result = await self.session.execute(claim_stmt(task_id))
        return bool(result.rowcount)

    async def mark_succeeded(self, task_id: uuid.UUID, result: dict) -> None:
        await self.session.execute(succeeded_stmt(task_id, result))

    async def mark_failed(self, task_id: uuid.UUID, error: str) -> None:
        await self.session.execute(failed_stmt(task_id, error))

    async def mark_pending_for_retry(self, task_id: uuid.UUID, error: str) -> None:
        await self.session.execute(retry_stmt(task_id, error))

"""Celery worker 的同步数据访问层。

worker 是同步进程，不能复用 API 的 AsyncSession 仓储；
状态流转语句与异步仓储共用 repositories/task_statements.py。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.chat_session import ChatSession
from app.models.enums import TaskStatus, TaskType
from app.models.message import Message
from app.models.task import Task
from app.repositories.task_statements import (
    claim_stmt,
    failed_stmt,
    retry_stmt,
    stale_pending_stmt,
    stale_running_stmt,
    succeeded_stmt,
)


def claim(db: Session, task_id: uuid.UUID) -> bool:
    result = db.execute(claim_stmt(task_id))
    return bool(result.rowcount)


def load_task(db: Session, task_id: uuid.UUID) -> Task:
    db.expire_all()
    db.commit()
    task = db.get(Task, task_id)
    if task is None:
        raise LookupError(f"任务 {task_id} 不存在")
    return task


def mark_succeeded(db: Session, task_id: uuid.UUID, result: dict) -> None:
    db.execute(succeeded_stmt(task_id, result))


def mark_failed(db: Session, task_id: uuid.UUID, error: str) -> None:
    db.execute(failed_stmt(task_id, error))


def mark_retry(db: Session, task_id: uuid.UUID, error: str) -> None:
    db.execute(retry_stmt(task_id, error))


def get_chat_session(db: Session, session_id: uuid.UUID) -> ChatSession | None:
    return db.get(ChatSession, session_id)


def list_messages(db: Session, session_id: uuid.UUID, *, limit: int) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def count_by_role(db: Session, session_id: uuid.UUID) -> dict[str, int]:
    stmt = (
        select(Message.role, func.count())
        .where(Message.session_id == session_id)
        .group_by(Message.role)
    )
    return {str(role.value): int(count) for role, count in db.execute(stmt).all()}


def message_time_range(
    db: Session, session_id: uuid.UUID
) -> tuple[datetime | None, datetime | None]:
    stmt = select(func.min(Message.created_at), func.max(Message.created_at)).where(
        Message.session_id == session_id
    )
    first_at, last_at = db.execute(stmt).one()
    return first_at, last_at


def purge_expired_sessions(db: Session, *, inactive_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=inactive_days)
    stmt = delete(ChatSession).where(
        ChatSession.deleted_at.is_not(None), ChatSession.deleted_at < cutoff
    )
    return db.execute(stmt).rowcount or 0


def stale_pending(
    db: Session, *, older_than_seconds: int, max_attempts: int
) -> list[tuple[uuid.UUID, TaskType]]:
    stmt = stale_pending_stmt(older_than_seconds=older_than_seconds, max_attempts=max_attempts)
    return [(row[0], row[1]) for row in db.execute(stmt).all()]


def stale_running(
    db: Session, *, older_than_seconds: int, max_attempts: int
) -> list[tuple[uuid.UUID, TaskType]]:
    stmt = stale_running_stmt(older_than_seconds=older_than_seconds, max_attempts=max_attempts)
    return [(row[0], row[1]) for row in db.execute(stmt).all()]


def reset_running_to_pending(db: Session, task_id: uuid.UUID) -> None:
    db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == TaskStatus.RUNNING)
        .values(status=TaskStatus.PENDING, finished_at=None)
    )

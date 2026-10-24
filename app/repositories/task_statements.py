"""任务状态流转的 SQL 语句构造。

异步仓储（API）和 Celery worker 的同步仓储都执行同一批语句，
保证状态机只有一份定义。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.sql import Select, Update

from app.models.enums import TaskStatus
from app.models.task import Task


def claim_stmt(task_id: uuid.UUID) -> Update:
    """pending -> running 的条件更新，返回 rowcount 为 0 表示没抢到。"""
    return (
        update(Task)
        .where(Task.id == task_id, Task.status == TaskStatus.PENDING)
        .values(
            status=TaskStatus.RUNNING,
            attempts=Task.attempts + 1,
            started_at=func.now(),
            error=None,
        )
    )


def succeeded_stmt(task_id: uuid.UUID, result: dict) -> Update:
    return (
        update(Task)
        .where(Task.id == task_id)
        .values(
            status=TaskStatus.SUCCEEDED,
            result=result,
            error=None,
            finished_at=datetime.now(UTC),
        )
    )


def failed_stmt(task_id: uuid.UUID, error: str) -> Update:
    return (
        update(Task)
        .where(Task.id == task_id)
        .values(status=TaskStatus.FAILED, error=error, finished_at=datetime.now(UTC))
    )


def retry_stmt(task_id: uuid.UUID, error: str) -> Update:
    """失败后放回 pending，让 Celery 的重投递能再次抢到；已尝试次数保留。"""
    return (
        update(Task)
        .where(Task.id == task_id)
        .values(status=TaskStatus.PENDING, error=error, finished_at=None)
    )


def stale_pending_stmt(*, older_than_seconds: int, max_attempts: int) -> Select:
    """长时间停留在 pending 且尝试次数未超限的任务，供补偿扫描重投。"""
    cutoff = datetime.now(UTC).timestamp() - older_than_seconds
    return select(Task.id, Task.type).where(
        Task.status == TaskStatus.PENDING,
        Task.attempts < max_attempts,
        func.extract("epoch", Task.created_at) < cutoff,
    )


def stale_running_stmt(*, older_than_seconds: int, max_attempts: int) -> Select:
    """超过硬超时仍在 running 的任务（worker 被杀、消息丢失），供补偿扫描重投。

    以 started_at 计时；超时的任务一定已超过 task_time_limit，
    原始进程不可能还活着，重置回 pending 是安全的。
    """
    cutoff = datetime.now(UTC).timestamp() - older_than_seconds
    return select(Task.id, Task.type).where(
        Task.status == TaskStatus.RUNNING,
        Task.attempts < max_attempts,
        func.extract("epoch", Task.started_at) < cutoff,
    )

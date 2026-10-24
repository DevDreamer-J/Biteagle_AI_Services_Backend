"""Celery 任务处理器。

所有任务都围绕 tasks 表的状态机执行：
claim（pending -> running）→ 业务逻辑 → succeeded / retry / failed。
claim 是条件更新，重复投递的消息不会重复执行。
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from celery import Task as CeleryTask
from celery.signals import worker_ready, worker_shutdown
from kombu import Exchange, Queue
from sqlalchemy.orm import Session

from app.clients.task_cache import set_task_state_sync, task_state_payload
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_sync_engine, get_sync_session_factory
from app.models.enums import TaskType
from app.models.message import Message
from app.models.task import Task
from app.workers import repository as repo
from app.workers.celery_app import celery_app
from app.workers.dispatch import (
    CLEANUP_EXPIRED_TASK,
    REQUEUE_STALE_TASK,
    SESSION_EXPORT_TASK,
    SESSION_STATS_TASK,
    dispatch_task,
)

configure_logging(get_settings())
logger = structlog.get_logger(__name__)

MAX_RETRIES = 3
RETRY_COUNTDOWNS = (10, 30, 60)
STALE_PENDING_SECONDS = 300
STALE_RUNNING_SECONDS = 600
CLEANUP_INACTIVE_DAYS = 30
EXPORT_MAX_MESSAGES = 500


def _refresh_cache(db: Session, task_id: uuid.UUID) -> None:
    task = repo.load_task(db, task_id)
    set_task_state_sync(task_state_payload(task))


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _session_stats(db: Session, task: Task) -> dict[str, Any]:
    session_id = task.session_id
    if session_id is None:
        raise ValueError("会话已被删除，无法统计")
    chat = repo.get_chat_session(db, session_id)
    if chat is None:
        raise ValueError("会话不存在")

    by_role = repo.count_by_role(db, session_id)
    first_at, last_at = repo.message_time_range(db, session_id)
    return {
        "session_id": str(session_id),
        "message_count": sum(by_role.values()),
        "by_role": by_role,
        "first_message_at": _iso(first_at),
        "last_message_at": _iso(last_at),
    }


def _session_export(db: Session, task: Task) -> dict[str, Any]:
    session_id = task.session_id
    if session_id is None:
        raise ValueError("会话已被删除，无法导出")
    chat = repo.get_chat_session(db, session_id)
    if chat is None:
        raise ValueError("会话不存在")

    messages = repo.list_messages(db, session_id, limit=EXPORT_MAX_MESSAGES)
    lines = [f"# {chat.title or '未命名会话'}", ""]
    for message in messages:
        lines.extend(_render_message(message))
    return {
        "session_id": str(session_id),
        "format": "markdown",
        "message_count": len(messages),
        "truncated": len(messages) >= EXPORT_MAX_MESSAGES,
        "content": "\n".join(lines),
    }


def _render_message(message: Message) -> list[str]:
    label = "用户" if message.role.value == "user" else "助手"
    return [f"## {label} · {_iso(message.created_at)}", "", message.content, ""]


def _execute(task: CeleryTask, task_id: str, handler: Any) -> dict[str, Any] | None:
    """统一的状态流转模板，绑定在 Celery 任务实例上使用。"""
    tid = uuid.UUID(task_id)
    with get_sync_session_factory()() as db:
        claimed = repo.claim(db, tid)
        db.commit()
        if not claimed:
            current = repo.load_task(db, tid)
            set_task_state_sync(task_state_payload(current))
            logger.info("task_skipped", task_id=task_id, status=current.status.value)
            return None

        _refresh_cache(db, tid)
        try:
            result = handler(db, repo.load_task(db, tid))
        except Exception as exc:
            db.rollback()
            error = f"{type(exc).__name__}: {exc}"[:2000]
            if task.request.retries < MAX_RETRIES:
                repo.mark_retry(db, tid, error)
                db.commit()
                _refresh_cache(db, tid)
                countdown = RETRY_COUNTDOWNS[min(task.request.retries, len(RETRY_COUNTDOWNS) - 1)]
                logger.warning(
                    "task_retrying",
                    task_id=task_id,
                    retries=task.request.retries,
                    countdown=countdown,
                    error=error,
                )
                raise task.retry(exc=exc, countdown=countdown) from exc

            repo.mark_failed(db, tid, error)
            db.commit()
            _refresh_cache(db, tid)
            logger.exception("task_failed", task_id=task_id, error=error)
            raise

        repo.mark_succeeded(db, tid, result)
        db.commit()
        _refresh_cache(db, tid)
        logger.info("task_succeeded", task_id=task_id)
        return result


@celery_app.task(bind=True, name=SESSION_STATS_TASK)
def session_stats(self: CeleryTask, task_id: str) -> dict[str, Any] | None:
    return _execute(self, task_id, _session_stats)


@celery_app.task(bind=True, name=SESSION_EXPORT_TASK)
def session_export(self: CeleryTask, task_id: str) -> dict[str, Any] | None:
    return _execute(self, task_id, _session_export)


@celery_app.task(name=CLEANUP_EXPIRED_TASK)
def cleanup_expired() -> int:
    """Beat 周期任务：物理清理软删除超过 30 天的会话（级联删消息）。"""
    try:
        with get_sync_session_factory()() as db:
            deleted = repo.purge_expired_sessions(db, inactive_days=CLEANUP_INACTIVE_DAYS)
            db.commit()
    except Exception as exc:
        logger.exception("cleanup_expired_failed", error=str(exc))
        raise
    logger.info("cleanup_expired_done", deleted=deleted)
    return deleted


@celery_app.task(name=REQUEUE_STALE_TASK)
def requeue_stale() -> int:
    """Beat 周期任务：重投长时间 pending / 卡在 running 的任务。

    重投的是同一个 task_id，claim 的条件更新保证不会并行重复执行；
    attempts 超过上限的任务保持原状态，等待人工排查。
    """
    try:
        with get_sync_session_factory()() as db:
            pending = repo.stale_pending(
                db,
                older_than_seconds=STALE_PENDING_SECONDS,
                max_attempts=MAX_RETRIES,
            )
            running = repo.stale_running(
                db,
                older_than_seconds=STALE_RUNNING_SECONDS,
                max_attempts=MAX_RETRIES,
            )
            for task_id, _ in running:
                repo.reset_running_to_pending(db, task_id)
            db.commit()
    except Exception as exc:
        logger.exception("requeue_stale_scan_failed", error=str(exc))
        raise

    stale: list[tuple[uuid.UUID, TaskType]] = [*pending, *running]
    dispatched = 0
    for task_id, task_type in stale:
        try:
            dispatch_task(task_id, task_type)
        except Exception as exc:
            logger.warning("requeue_stale_dispatch_failed", task_id=str(task_id), error=str(exc))
            continue
        dispatched += 1

    if dispatched:
        logger.info("requeue_stale_done", found=len(stale), dispatched=dispatched)
    return dispatched


@worker_shutdown.connect
def _on_worker_shutdown(**_: Any) -> None:
    dispose_sync_engine()


@worker_ready.connect
def _declare_dead_letter_queue(**_: Any) -> None:
    """显式声明死信队列。

    worker 只消费 ai.tasks，不会自动声明 ai.dead；
    缺了它，被拒绝的消息会因路由不到队列而直接丢弃。
    """
    dlx = Exchange("ai.dlx", type="direct", durable=True)
    dead = Queue("ai.dead", dlx, routing_key="ai.dead", durable=True)
    try:
        with celery_app.connection_for_write() as connection:
            with connection.channel() as channel:
                dead(channel).declare()
    except Exception as exc:
        logger.warning("dead_queue_declare_failed", error=str(exc))


__all__ = [
    "cleanup_expired",
    "requeue_stale",
    "session_export",
    "session_stats",
]

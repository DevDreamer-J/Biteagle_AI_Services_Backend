"""任务分发：业务任务类型与 Celery 任务名的唯一映射。"""

from __future__ import annotations

import uuid

from app.models.enums import TaskType
from app.workers.celery_app import celery_app

SESSION_STATS_TASK = "tasks.session_stats"
SESSION_EXPORT_TASK = "tasks.session_export"
CLEANUP_EXPIRED_TASK = "tasks.cleanup_expired"
REQUEUE_STALE_TASK = "tasks.requeue_stale"

TASK_NAME_BY_TYPE: dict[TaskType, str] = {
    TaskType.SESSION_STATS: SESSION_STATS_TASK,
    TaskType.SESSION_EXPORT: SESSION_EXPORT_TASK,
}


def dispatch_task(task_id: uuid.UUID, task_type: TaskType) -> None:
    """投递消息。业务主键直接用作 Celery task_id，便于双向追踪。

    用 apply_async 而非 send_task：后者不遵守 task_always_eager，
    eager 模式下（测试）需要同步执行任务处理器。
    """
    task_name = TASK_NAME_BY_TYPE[task_type]
    task = celery_app.tasks[task_name]
    task.apply_async(args=[str(task_id)], task_id=str(task_id))

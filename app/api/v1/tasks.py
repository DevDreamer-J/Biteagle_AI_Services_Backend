"""异步任务接口：提交任务、轮询状态、查看历史。

任务状态以 PostgreSQL 为准，Redis 只做读缓存；
提交接口返回 202，客户端用返回的 id 轮询 GET /v1/tasks/{id}。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Header, Query, status

from app.api.deps import CurrentUser, RateLimitedByUser, SessionDep
from app.clients.idempotency import get_idempotent, set_idempotent
from app.clients.task_cache import get_task_state, set_task_state, task_state_payload
from app.core.errors import NotFoundError, ServiceUnavailableError, ValidationFailedError
from app.models.enums import TaskStatus, TaskType
from app.models.task import Task
from app.repositories.session_repo import SessionRepository
from app.repositories.task_repo import TaskRepository
from app.schemas.common import Page
from app.schemas.task import TaskCreate, TaskRead
from app.workers.dispatch import dispatch_task

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]

SESSION_TASK_TYPES = {TaskType.SESSION_STATS, TaskType.SESSION_EXPORT}


def _owned_task(task: Task | None, user_id: uuid.UUID) -> Task:
    """他人任务统一返回 404，避免泄漏任务是否存在。"""
    if task is None or task.user_id != user_id:
        raise NotFoundError("任务不存在")
    return task


async def _validate_session(
    session: SessionDep, user_id: uuid.UUID, task_type: TaskType, session_id: uuid.UUID | None
) -> None:
    if task_type not in SESSION_TASK_TYPES:
        return
    if session_id is None:
        raise ValidationFailedError("该任务类型必须提供 session_id")
    chat = await SessionRepository(session).get(session_id)
    if chat is None or chat.user_id != user_id:
        raise NotFoundError("会话不存在")


async def _read_task(task: Task) -> TaskRead:
    cached = await get_task_state(task.id)
    if cached is not None:
        return TaskRead.model_validate(cached)
    state = task_state_payload(task)
    await set_task_state(state)
    return TaskRead.model_validate(state)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskRead,
    summary="提交异步任务",
    description="写入任务记录并投递到 RabbitMQ，返回 202；用 id 轮询状态。",
)
async def create_task(
    payload: TaskCreate,
    session: SessionDep,
    user: CurrentUser,
    _: RateLimitedByUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TaskRead:
    await _validate_session(session, user.id, payload.type, payload.session_id)

    namespace = f"task:{user.id}"
    if idempotency_key is not None:
        if not 1 <= len(idempotency_key) <= 200:
            raise ValidationFailedError("Idempotency-Key 长度需在 1-200 之间")
        cached = await get_idempotent(namespace, idempotency_key)
        if cached is not None:
            return TaskRead.model_validate(cached)

    repo = TaskRepository(session)
    task_id = uuid.uuid4()
    task = await repo.create(
        user_id=user.id,
        type=payload.type,
        payload={"session_id": str(payload.session_id)} if payload.session_id else {},
        session_id=payload.session_id,
        task_id=task_id,
    )
    await session.commit()
    await session.refresh(task)

    try:
        # send_task 是同步网络调用，放到线程里避免阻塞事件循环
        await asyncio.to_thread(dispatch_task, task_id, payload.type)
    except Exception as exc:
        logger.warning("task_dispatch_failed", task_id=str(task_id), error=str(exc))
        await repo.mark_failed(task_id, f"DispatchError: {exc}"[:2000])
        await session.commit()
        raise ServiceUnavailableError("任务队列不可用，请稍后重试") from exc

    # 重新读取：Celery eager 模式下任务可能已同步执行完毕，
    # 异步模式下通常仍是 pending，两种场景都以数据库最新状态为准
    await session.refresh(task)
    state = task_state_payload(task)
    await set_task_state(state)
    if idempotency_key is not None:
        await set_idempotent(namespace, idempotency_key, state)
    return TaskRead.model_validate(state)


@router.get("/{task_id}", response_model=TaskRead, summary="任务状态")
async def get_task(task_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> TaskRead:
    task = _owned_task(await TaskRepository(session).get(task_id), user.id)
    return await _read_task(task)


@router.get("", response_model=Page[TaskRead], summary="任务列表")
async def list_tasks(
    session: SessionDep,
    user: CurrentUser,
    limit: Limit = 20,
    offset: Offset = 0,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
) -> Page[TaskRead]:
    repo = TaskRepository(session)
    items = await repo.list_for_user(user.id, status=status_filter, limit=limit, offset=offset)
    total = await repo.count_for_user(user.id, status=status_filter)
    return Page[TaskRead](
        items=[TaskRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )

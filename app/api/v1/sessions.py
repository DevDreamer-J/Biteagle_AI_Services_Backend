"""会话与消息接口。除注册外全部要求 X-API-Key。"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, RateLimitedByUser, SessionDep
from app.core.errors import NotFoundError
from app.models.chat_session import ChatSession
from app.models.enums import MessageRole
from app.models.user import User
from app.repositories.message_repo import MessageRepository
from app.repositories.session_repo import SessionRepository
from app.schemas.common import Page
from app.schemas.message import MessageCreate, MessageRead
from app.schemas.session import SessionCreate, SessionRead, SessionUpdate

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


async def _owned_session(session_id: uuid.UUID, session: SessionDep, user: User) -> ChatSession:
    """统一用 404 而不是 403，避免泄漏他人资源是否存在。"""
    chat = await SessionRepository(session).get(session_id)
    if chat is None or chat.user_id != user.id:
        raise NotFoundError("会话不存在")
    return chat


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=SessionRead, summary="创建会话"
)
async def create_session(
    payload: SessionCreate, session: SessionDep, user: CurrentUser, _: RateLimitedByUser
) -> SessionRead:
    chat = await SessionRepository(session).create(user_id=user.id, title=payload.title)
    await session.commit()
    await session.refresh(chat)
    return SessionRead.model_validate(chat)


@router.get("", response_model=Page[SessionRead], summary="会话列表")
async def list_sessions(
    session: SessionDep,
    user: CurrentUser,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[SessionRead]:
    repo = SessionRepository(session)
    items = await repo.list_for_user(user.id, limit=limit, offset=offset)
    total = await repo.count_for_user(user.id)
    return Page[SessionRead](
        items=[SessionRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{session_id}", response_model=SessionRead, summary="会话详情")
async def get_session(session_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> SessionRead:
    chat = await _owned_session(session_id, session, user)
    return SessionRead.model_validate(chat)


@router.patch("/{session_id}", response_model=SessionRead, summary="更新会话")
async def update_session(
    session_id: uuid.UUID,
    payload: SessionUpdate,
    session: SessionDep,
    user: CurrentUser,
    _: RateLimitedByUser,
) -> SessionRead:
    chat = await _owned_session(session_id, session, user)
    if payload.title is not None:
        chat.title = payload.title
    if payload.is_archived is not None:
        chat.is_archived = payload.is_archived
    await session.commit()
    await session.refresh(chat)
    return SessionRead.model_validate(chat)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除会话（软删除）",
)
async def delete_session(
    session_id: uuid.UUID, session: SessionDep, user: CurrentUser, _: RateLimitedByUser
) -> Response:
    chat = await _owned_session(session_id, session, user)
    await SessionRepository(session).soft_delete(chat)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{session_id}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageRead,
    summary="追加消息",
    description="写入消息并刷新会话的 last_message_at。",
)
async def create_message(
    session_id: uuid.UUID,
    payload: MessageCreate,
    session: SessionDep,
    user: CurrentUser,
    _: RateLimitedByUser,
) -> MessageRead:
    chat = await _owned_session(session_id, session, user)
    message = await MessageRepository(session).create(
        session_id=chat.id, role=MessageRole(payload.role), content=payload.content
    )
    await SessionRepository(session).touch_last_message(chat)
    await session.commit()
    await session.refresh(message)
    return MessageRead.model_validate(message)


@router.get(
    "/{session_id}/messages",
    response_model=Page[MessageRead],
    summary="消息列表",
    description="ascending=true 按时间正序，false 取最近的在前。",
)
async def list_messages(
    session_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    limit: Limit = 50,
    offset: Offset = 0,
    ascending: bool = True,
) -> Page[MessageRead]:
    chat = await _owned_session(session_id, session, user)
    repo = MessageRepository(session)
    items = await repo.list_by_session(chat.id, limit=limit, offset=offset, ascending=ascending)
    total = await repo.count_by_session(chat.id)
    return Page[MessageRead](
        items=[MessageRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )

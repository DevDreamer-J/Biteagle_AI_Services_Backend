"""用户接口：注册与当前用户信息。"""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, RateLimitedByIP, SessionDep
from app.core.errors import ConflictError
from app.core.security import generate_api_key, hash_api_key
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserCreate, UserCreated, UserRead

router = APIRouter(prefix="/v1/users", tags=["users"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=UserCreated,
    summary="注册用户",
    description="返回的 api_key 明文只出现这一次，后续请求需放在 X-API-Key 请求头里。",
)
async def register(payload: UserCreate, session: SessionDep, _: RateLimitedByIP) -> UserCreated:
    repo = UserRepository(session)
    if await repo.get_by_email(payload.email) is not None:
        raise ConflictError("邮箱已被注册")

    raw_key = generate_api_key()
    try:
        user = await repo.create(
            email=payload.email,
            display_name=payload.display_name,
            api_key_hash=hash_api_key(raw_key),
        )
        await session.commit()
    except IntegrityError as exc:
        # 并发注册同一邮箱时唯一索引兜底
        await session.rollback()
        raise ConflictError("邮箱已被注册") from exc

    await session.refresh(user)
    return UserCreated(**UserRead.model_validate(user).model_dump(), api_key=raw_key)


@router.get("/me", response_model=UserRead, summary="当前用户")
async def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)

"""用户相关模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# 不引入 email-validator 依赖，用约束正则做基础校验
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class UserCreate(BaseModel):
    email: Email = Field(examples=["alice@example.com"])
    display_name: DisplayName = Field(examples=["Alice"])


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool
    created_at: datetime


class UserCreated(UserRead):
    """注册响应：api_key 明文只在这里出现一次。"""

    api_key: str = Field(description="请立即保存，服务端只存 SHA-256 摘要")

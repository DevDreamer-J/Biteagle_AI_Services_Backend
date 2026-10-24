"""消息相关模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class MessageCreate(BaseModel):
    role: Annotated[str, StringConstraints(pattern="^(user|assistant)$")] = Field(
        default="user", description="只允许 user / assistant，system 由服务端内部使用"
    )
    content: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)
    ]


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    created_at: datetime

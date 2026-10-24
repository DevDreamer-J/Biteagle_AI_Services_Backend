"""通用请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Page[ItemT](BaseModel):
    items: list[ItemT]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)

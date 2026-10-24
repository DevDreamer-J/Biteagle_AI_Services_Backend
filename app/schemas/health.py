"""健康检查响应模型。"""

from pydantic import BaseModel, Field


class Liveness(BaseModel):
    status: str = Field(examples=["ok"])
    app: str
    version: str


class Readiness(BaseModel):
    status: str = Field(examples=["ok", "degraded"])
    checks: dict[str, str] = Field(examples=[{"database": "ok", "redis": "ok"}])

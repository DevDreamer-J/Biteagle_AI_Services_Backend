"""业务枚举与数据库枚举列构造。

所有枚举都用 VARCHAR + CHECK 约束（native_enum=False）实现，
避免 PostgreSQL 原生 ENUM 在 Alembic 迁移中增删值时的额外 DDL 成本。
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class TaskType(StrEnum):
    SESSION_STATS = "session_stats"
    SESSION_EXPORT = "session_export"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


def enum_column(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """按枚举的 value 存储（SAEnum 默认存 name，这里显式改为 value）。"""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
    )

"""模型公共组件：UUID 主键、时间戳、枚举列类型。"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum as SAEnum, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def str_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """字符串枚举：落库为 VARCHAR + CHECK，不用 PG 原生 enum，扩值不必改类型。"""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        validate_strings=True,
        create_constraint=True,
        values_callable=lambda enum: [member.value for member in enum],
    )

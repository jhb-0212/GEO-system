"""媒体资源矩阵的平台级目录配置。

这张表不挂 project_id：矩阵是对外展示的资源类型目录，多个客户、多个项目共用一份。
每个客户各自的渠道台账仍然按 project_id 隔离，二者不混用。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class MediaMatrixConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "media_matrix_configs"

    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(255))

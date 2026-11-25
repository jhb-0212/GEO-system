"""项目级卖点清单：用于逐条核对内容是否提到并说清具体口径。"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class SellingPoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "selling_points"
    __table_args__ = (
        UniqueConstraint("project_id", "label", name="uq_selling_points_project_label"),
        Index("ix_selling_points_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    # 期望在正文里出现的事实口径，例如「每班不超过 6 人」「3980 元」
    value_text: Mapped[str | None] = mapped_column(Text)
    # 同义说法/关键词；用于判断“提到了但没给出具体口径”
    aliases: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="true")
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

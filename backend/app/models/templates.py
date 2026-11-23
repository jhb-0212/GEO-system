"""内容工厂模板：按「渠道 × 题型」沉淀固定骨架，生成时只填槽位。

模板只存骨架与槽位定义，不存正文；生成出来的是普通 draft 内容，
仍要走路审核流程——模板不能成为绕过审核的后门。
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class ContentTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_templates"
    __table_args__ = (
        Index("ix_content_templates_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # 目标渠道类别与题型：用代码常量，不建原生枚举，扩产线不必再迁移
    channel_category: Mapped[str | None] = mapped_column(String(32))
    question_type: Mapped[str | None] = mapped_column(String(16))
    # 骨架用 {{槽位名}} 占位；slots 由服务端从骨架解析后落库，前端不自行解释
    skeleton: Mapped[str] = mapped_column(Text, nullable=False)
    slots: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

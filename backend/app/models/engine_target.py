"""引擎期望：把「这条渠道内容希望被哪个引擎引用」从自由 JSON 拆成可查询的结构。

口径边界（重要）：
- 投喂目标永远是**渠道**，引擎是「期望」而不是投放对象，本表只表达期望与观察；
- `priority` 只按「该渠道在各引擎下被复核引用的条数」排序，不合成任何总分；
- 一行一引擎，允许一条渠道挂多个引擎，避免 JSON 里塞数组无法按引擎统计。
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class EngineTarget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "engine_targets"
    __table_args__ = (
        UniqueConstraint("project_id", "channel_id", "engine_id", name="uq_engine_targets_project_channel_engine"),
        Index("ix_engine_targets_project_channel", "project_id", "channel_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False
    )
    content_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_plans.id", ondelete="SET NULL")
    )
    engine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_engines.id", ondelete="RESTRICT"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    note: Mapped[str | None] = mapped_column(Text)
    # manual=人工确认；observed=由实测引用推导后人工确认过的快照来源标记
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

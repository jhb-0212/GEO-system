"""G1/G2 生成批次：缺口 → 简报 → 批量出稿 → 审稿队列。

三条边界（改代码前先看）：

1. **不接受空手起题**：批次的候选项只能来自已有证据——机会中心的缺口（竞品被引用
   而自己没被引用），或「监测过但从没提及品牌」的问题。选题必须可回溯到某个样本/引用。
2. **默认不调模型**：出稿方式先只做模板合成（`GenerationMode.TEMPLATE`），
   正文由品牌档案、企业事实、FAQ、被引用来源拼装而成，可复现、不花钱。
   要接模型必须显式传 `engine_code`，并另有开关（见服务层 `model_generation_enabled`）。
3. **不自动发布**：批次只产出草稿，落在 `generation_items` 上等人工审；
   发布仍走内容审核 → 发布任务，不在这里直通。
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import GenerationBatchStatus, GenerationItemStatus, GenerationMode


class GenerationBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "generation_batches"
    __table_args__ = (
        # 来源必须是「已有证据」的三类之一；纠正稿只接人工判定为负面的引用
        CheckConstraint(
            "source in ('opportunity','question','remediation')",
            name="ck_generation_batches_source",
        ),
        Index("ix_generation_batches_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[GenerationBatchStatus] = mapped_column(
        str_enum(GenerationBatchStatus, "generation_batch_status"),
        nullable=False,
        default=GenerationBatchStatus.QUEUED,
        server_default=GenerationBatchStatus.QUEUED.value,
    )
    # 空字符串 = 纯模板合成；有值 = 指定了引擎（当前只登记，不自动调用付费模型）
    engine_code: Mapped[str | None] = mapped_column(String(64))
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    drafted_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class GenerationItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "generation_items"
    __table_args__ = (
        Index("ix_generation_items_batch_order", "batch_id", "sort_order"),
        Index("ix_generation_items_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generation_batches.id", ondelete="CASCADE"), nullable=False
    )
    # 来源可回溯：至少有一个不为空，两边都空的行没有存在的理由
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    brief: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[GenerationItemStatus] = mapped_column(
        str_enum(GenerationItemStatus, "generation_item_status"),
        nullable=False,
        default=GenerationItemStatus.PENDING,
        server_default=GenerationItemStatus.PENDING.value,
    )
    generation_mode: Mapped[GenerationMode] = mapped_column(
        str_enum(GenerationMode, "generation_mode"),
        nullable=False,
        default=GenerationMode.TEMPLATE,
        server_default=GenerationMode.TEMPLATE.value,
    )
    draft_body: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 审稿状态：草稿进队列后由人处理，机器不自动放行
    reviewed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

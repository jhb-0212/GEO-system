"""机会中心：把引用缺口、事实纠错和网站修复变成可指派、可评分的运营任务。"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import OpportunityGapType, OpportunityStatus


class Opportunity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """证据驱动的优化机会。

    六因子原始分保存在 `score_factors`，权重保存在 `score_weights`；
    `priority_score` 是落库时算好的加权分，列表排序只读这个字段，不在查询时重算。
    """

    __tablename__ = "opportunities"
    __table_args__ = (
        Index(
            "ix_opportunities_project_status_score",
            "project_id",
            "status",
            "priority_score",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    gap_type: Mapped[OpportunityGapType] = mapped_column(
        str_enum(OpportunityGapType, "opportunity_gap_type"), nullable=False
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    sample_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("monitoring_samples.id", ondelete="SET NULL")
    )
    # 证据引用：sample / citation / gap / fact 等 ID 列表，保留创建时的判断依据。
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    score_factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    score_weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    priority_score: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[OpportunityStatus] = mapped_column(
        str_enum(OpportunityStatus, "opportunity_status"),
        nullable=False,
        default=OpportunityStatus.OPEN,
        server_default=OpportunityStatus.OPEN.value,
    )
    linked_content_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_plans.id", ondelete="SET NULL")
    )
    linked_content_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="SET NULL")
    )
    linked_publish_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("publish_tasks.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)

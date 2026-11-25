"""线索归因：把线索挂到具体引擎、问题、监测样本与文章。

一条线索一行；sample_id / question_id 不在访客页面明文展示，只由后端按令牌/链接
参数解析后落库，避免访客看到内部 ID。
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class LeadAttribution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lead_attributions"
    __table_args__ = (
        UniqueConstraint("lead_id", name="uq_lead_attributions_lead"),
        Index("ix_lead_attributions_project_sample", "project_id", "sample_id"),
        Index("ix_lead_attributions_project_question", "project_id", "question_id"),
        Index("ix_lead_attributions_project_engine", "project_id", "engine_id"),
        Index("ix_lead_attributions_project_article", "project_id", "content_item_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    sample_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("monitoring_samples.id", ondelete="SET NULL")
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    engine_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_engines.id", ondelete="SET NULL")
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL")
    )
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="SET NULL")
    )
    article_url: Mapped[str | None] = mapped_column(String(512))
    answer_kind: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="low", server_default="low")
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

"""情绪标注：只存人工判断，不存原文副本。

原文（标题 / 摘要 / 链接）始终回读 `monitoring_citations`，本表只记录「谁在什么时候
把哪条引用原文判成正/中/负」。这样引用被复核修正时，情绪页不会展示过期副本。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import SentimentPolarity


class SentimentLabel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sentiment_labels"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "citation_id", "labeled_by",
            name="uq_sentiment_labels_project_citation_labeler",
        ),
        Index("ix_sentiment_labels_project_polarity", "project_id", "polarity"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    citation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_citations.id", ondelete="CASCADE"), nullable=False
    )
    polarity: Mapped[SentimentPolarity] = mapped_column(
        str_enum(SentimentPolarity, "sentiment_polarity"),
        nullable=False,
    )
    # 人工分级字段：先留空，等有明确的业务分级标准再填，不预设结论
    grade: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    labeled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    labeled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

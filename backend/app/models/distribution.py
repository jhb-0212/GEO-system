"""投喂批次：把一批已审核内容指向目标 AI 平台，进投喂前先过预检。

设计边界：
- 批次不复制内容正文，只记 content_version 引用；
- 预检结果随批次落库（`precheck`），但页面展示以「重新预检」的最新结果为准；
- 预检不过一律 blocked，不允许直接标记已投喂——避免把关口写在人脑里。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import DistributionBatchStatus


class DistributionBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "distribution_batches"
    __table_args__ = (
        Index("ix_distribution_batches_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[DistributionBatchStatus] = mapped_column(
        str_enum(DistributionBatchStatus, "distribution_batch_status"),
        nullable=False,
        default=DistributionBatchStatus.BLOCKED,
        server_default=DistributionBatchStatus.BLOCKED.value,
    )
    target_engines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    precheck: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DistributionBatchItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "distribution_batch_items"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("distribution_batches.id", ondelete="CASCADE"), nullable=False
    )
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)

"""渠道改编：母稿 → 渠道稿的血缘与跟版状态。

只记血缘与来源哈希，不复制正文；正文仍落在 content_versions，
渠道稿本身就是普通 `kind=channel` 内容，照常走审核。
"""

import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class ContentDerivation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_derivations"
    __table_args__ = (
        UniqueConstraint("project_id", "channel_item_id", name="uq_content_derivations_channel_item"),
        Index("ix_content_derivations_project_master", "project_id", "master_item_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    master_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False
    )
    channel_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    # 改编当时的母稿版本与哈希：母稿再改，这里不动，靠两者不一致判定「没跟版」
    source_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=False
    )
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    synced_at: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

"""品牌搜索量快照：先支持 CSV/手工导入，不依赖指数 API。"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class BrandSearchSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "brand_search_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "platform", "snapshot_date", name="uq_brand_search_project_platform_date"),
        Index("ix_brand_search_project_date", "project_id", "snapshot_date"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    search_volume: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

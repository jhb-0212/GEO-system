"""K4 百科词条：站内起草 → 提交审核 → 通过/驳回 → 登记第三方平台外链。

三条边界（改代码前先看）：

1. **词条不等于官网页面**：官网事实页在 `public_pages`，百科词条是投放到百度百科、
   搜狗百科、抖音百科等第三方平台的正文，这里只做「写、审、登链接」。
2. **不代发布**：系统不调第三方百科的编辑接口（各家都不开放稳定写接口），
   发布动作由人在平台提交后回填 `published_url`，系统只记事实与时间。
3. **驳回可改、已发布不可改**：只允许草稿/已驳回编辑；已发布词条要改必须新建版本，
   避免外链与正文对不上。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import EncyclopediaStatus


class EncyclopediaEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "encyclopedia_entries"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_encyclopedia_entries_project_slug"),
        Index("ix_encyclopedia_entries_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    # 词条名的稳定标识，同一项目内唯一；不外露
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # 目标平台：baidu_baike / sogou_baike / douyin_baike / wikipedia / other
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # 参考资料：[{title, url, note}]，审核时逐条看来源是否可核验
    references: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    status: Mapped[EncyclopediaStatus] = mapped_column(
        str_enum(EncyclopediaStatus, "encyclopedia_status"),
        nullable=False,
        default=EncyclopediaStatus.DRAFT,
        server_default=EncyclopediaStatus.DRAFT.value,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""页面级发布审批：逐页登记 URL、页型和权限，不随渠道审批自动放行。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import CitationPageType, PageApprovalStatus, PagePermission


class PageApproval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一条 URL 一行审批。

    `url_key` 是去协议/跟踪参数后的跨协议比对键，同一项目、渠道、页面不能重复登记；
    `normalized_url` 保留可展示的规范 URL。`permission=third_party` 的页面可以
    作为引用来源审批，但不能作为官方发布页通过回执闸门。
    """

    __tablename__ = "page_approvals"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "channel_id", "url_key",
            name="uq_page_approvals_project_channel_url",
        ),
        Index("ix_page_approvals_project_status", "project_id", "status"),
        Index("ix_page_approvals_project_page_type", "project_id", "page_type"),
        Index("ix_page_approvals_channel", "channel_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    page_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_key: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    page_type: Mapped[CitationPageType] = mapped_column(
        str_enum(CitationPageType, "page_approval_page_type"), nullable=False
    )
    permission: Mapped[PagePermission] = mapped_column(
        str_enum(PagePermission, "page_permission"), nullable=False
    )
    status: Mapped[PageApprovalStatus] = mapped_column(
        str_enum(PageApprovalStatus, "page_approval_status"),
        nullable=False,
        default=PageApprovalStatus.PENDING,
        server_default=PageApprovalStatus.PENDING.value,
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)

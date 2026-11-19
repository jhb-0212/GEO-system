"""渠道台账：渠道定义、分类、域名映射独立维护，证据模块只引用 channel_id。

未知域名先进待归类队列（status=review_pending），人工确认结果不被自动识别覆盖。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    ReviewDecision,
)


class Channel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_channels_project_code"),
        Index(
            "uq_channels_project_primary_domain",
            "project_id",
            "primary_domain",
            unique=True,
            postgresql_where=text("primary_domain IS NOT NULL"),
        ),
        Index("ix_channels_project_category_status", "project_id", "category", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[ChannelCategory] = mapped_column(
        str_enum(ChannelCategory, "channel_category"), nullable=False
    )
    status: Mapped[ChannelStatus] = mapped_column(
        str_enum(ChannelStatus, "channel_status"),
        nullable=False,
        default=ChannelStatus.CANDIDATE,
        server_default=ChannelStatus.CANDIDATE.value,
    )
    primary_domain: Mapped[str | None] = mapped_column(String(255))
    # 人工发布入口：发布后台与登录页分开存，前端据此给出“去哪里发”的明确入口
    publish_url: Mapped[str | None] = mapped_column(String(512))
    login_url: Mapped[str | None] = mapped_column(String(512))
    # 渠道负责人：首月运营必须把“谁负责发布/维护”落到台账上，而不是只存在聊天记录里。
    owner_name: Mapped[str | None] = mapped_column(String(128))
    owner_contact: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )
    # 准入审批：与业务四态正交。未准入渠道不能建发布任务、不能挂接引用回执。
    approval_status: Mapped[ChannelApprovalStatus] = mapped_column(
        str_enum(ChannelApprovalStatus, "channel_approval_status"),
        nullable=False,
        default=ChannelApprovalStatus.PENDING_REVIEW,
        server_default=ChannelApprovalStatus.PENDING_REVIEW.value,
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(Text)


class ChannelAlias(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """域名 → 渠道映射：一个渠道可对应多个域名或历史名称。"""

    __tablename__ = "channel_aliases"
    __table_args__ = (
        UniqueConstraint("project_id", "domain", name="uq_channel_aliases_project_domain"),
        Index("ix_channel_aliases_channel", "channel_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_name: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)


class ChannelApproval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """渠道准入审批周期记录：一行一次提交→审批，留提交人/审批人/时间/结论/意见。

    驳回后重新提交会追加新的一行周期，历史结论不被覆盖；主表 `Channel` 冗余当前
    准入状态供门禁快查，本表提供完整审批轨迹。
    """

    __tablename__ = "channel_approvals"
    __table_args__ = (
        Index("ix_channel_approvals_project_channel", "project_id", "channel_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[ReviewDecision | None] = mapped_column(
        str_enum(ReviewDecision, "channel_approval_decision")
    )
    comment: Mapped[str | None] = mapped_column(Text)

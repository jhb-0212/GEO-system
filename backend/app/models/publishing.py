"""发布管理：账号、发布任务、发布尝试、平台回执。

幂等键 = 账号 + 渠道 + 内容版本 + 任务ID；回执不明时进 unknown/needs_review，先核实不重发。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import AttemptResult, PublishMode, PublishTaskStatus


class PublishAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """渠道发布账号：凭证只存引用键，真实密钥放服务端密钥管理，不进库、不进前端。"""

    __tablename__ = "publish_accounts"
    __table_args__ = (
        UniqueConstraint("project_id", "channel_id", "account_name", name="uq_publish_accounts_project_channel_name"),
        UniqueConstraint("oauth_connection_id", name="uq_publish_accounts_oauth_connection"),
        Index("ix_publish_accounts_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False
    )
    account_name: Mapped[str] = mapped_column(String(128), nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(255))
    # 可选绑定平台 OAuth 连接；一个连接只能绑定一个发布账号。令牌本体仍只在
    # oauth_connections 的密文列里，发布账号只保存连接 ID，不复制 token。
    oauth_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("oauth_connections.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    notes: Mapped[str | None] = mapped_column(Text)


class PublishTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "publish_tasks"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "channel_id",
            "version_id",
            "task_key",
            name="uq_publish_tasks_idempotency",
        ),
        UniqueConstraint("idempotency_key", name="uq_publish_tasks_idempotency_key"),
        Index("ix_publish_tasks_project_status", "project_id", "status"),
        Index("ix_publish_tasks_scheduled", "project_id", "scheduled_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    serial_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        server_default=text("nextval('publish_tasks_serial_no_seq')"),
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="RESTRICT"), nullable=False
    )
    # 由投喂批次确认时生成的任务带批次 id；手工建单为空。
    # 有了这条边，闭环看板/新鲜度/收录检测才能反向追到「哪一批投喂」。
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("distribution_batches.id", ondelete="SET NULL"), index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publish_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    task_key: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # 内容版本关联的监测引用 trace；只有唯一 trace 时继承，多条时不猜
    trace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    publish_mode: Mapped[PublishMode] = mapped_column(
        str_enum(PublishMode, "publish_mode"),
        nullable=False,
        default=PublishMode.MANUAL,
        server_default=PublishMode.MANUAL.value,
    )
    status: Mapped[PublishTaskStatus] = mapped_column(
        str_enum(PublishTaskStatus, "publish_task_status"),
        nullable=False,
        default=PublishTaskStatus.PENDING,
        server_default=PublishTaskStatus.PENDING.value,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_task_id: Mapped[str | None] = mapped_column(String(128))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PublishAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "publish_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uq_publish_attempts_task_attempt"),
        Index("ix_publish_attempts_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publish_tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mode: Mapped[PublishMode] = mapped_column(str_enum(PublishMode, "attempt_mode"), nullable=False)
    result: Mapped[AttemptResult] = mapped_column(
        str_enum(AttemptResult, "attempt_result"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_note: Mapped[str | None] = mapped_column(Text)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PublishReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """平台回执：结案凭证。人工发布填真实 URL 后结案。"""

    __tablename__ = "publish_receipts"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "id", name="uq_publish_receipts_project_id_id"
        ),
        ForeignKeyConstraint(
            ["project_id", "budget_approval_id"],
            ["budget_approvals.project_id", "budget_approvals.id"],
            name="fk_publish_receipts_project_budget",
            ondelete="RESTRICT",
        ),
        Index("ix_publish_receipts_project_task", "project_id", "task_id"),
        Index("ix_publish_receipts_budget", "budget_approval_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publish_tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("publish_attempts.id", ondelete="SET NULL")
    )
    published_url: Mapped[str] = mapped_column(Text, nullable=False)
    # 高风险页面的逐页审批凭证；普通页面允许为空。
    page_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_approvals.id", ondelete="SET NULL")
    )
    receipt_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # P76：回执可逐条挂到已批准的媒体投放预算；一条回执最多挂一个预算。
    budget_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget_approvals.id", ondelete="RESTRICT")
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 渠道侧三态之一：可访问。回抓页面本身，区别于「被搜索引擎收录」与「被 AI 引用」。
    # 空 = 还没查过；False 只代表这次抓取明确 404/410，网络失败只记 error 不改结论。
    last_reachable: Mapped[bool | None] = mapped_column(Boolean)
    last_reachability_status: Mapped[int | None] = mapped_column(Integer)
    last_reachability_error: Mapped[str | None] = mapped_column(String(64))
    last_reachability_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublishVisibilityCheck(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """发布可见性检测：发出去的页面能不能被搜索引擎检索到。

    只做诊断，是「发布 → 回执 → 被检索 → 被 AI 引用」中间那层的观测值；
    **不参与渠道归因**（渠道效果只认 `monitoring_citations.channel_id`）。
    上游失败时写 `error_code` 且 `matched` 保持 false，避免把"没查成"当成"没收录"。
    """

    __tablename__ = "publish_visibility_checks"
    __table_args__ = (
        Index("ix_publish_visibility_checks_project_checked", "project_id", "checked_at"),
        Index("ix_publish_visibility_checks_receipt", "receipt_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publish_receipts.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    matched: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    position: Mapped[int | None] = mapped_column(Integer)
    matched_url: Mapped[str | None] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    site: Mapped[str | None] = mapped_column(String(255))
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    request_id: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))

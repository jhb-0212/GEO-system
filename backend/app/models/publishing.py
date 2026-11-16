"""发布管理：账号、发布任务、发布尝试、平台回执。

幂等键 = 账号 + 渠道 + 内容版本 + 任务ID；回执不明时进 unknown/needs_review，先核实不重发。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="RESTRICT"), nullable=False
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
    __table_args__ = (Index("ix_publish_receipts_project_task", "project_id", "task_id"),)

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
    receipt_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

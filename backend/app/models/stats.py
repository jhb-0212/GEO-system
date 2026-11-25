"""统计快照：每轮冻结一份不可变统计结果，防止历史趋势被配置变更重解释。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
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
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class StatSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一轮一份冻结快照：范围、分母、指标和规则版本一起留痕。"""

    __tablename__ = "stat_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "round_id", name="uq_stat_snapshots_project_round"),
        Index("ix_stat_snapshots_project_captured_at", "project_id", "captured_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    round_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_rounds.id", ondelete="CASCADE"), nullable=False
    )
    captured_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # scope 记录问题版本、引擎入口、采样模式、时间窗、轮次快照 hash 等测量范围
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # metrics 存 overview / answer-kind / by-engine / by-question / geo / sources 的冻结副本
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    definitions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    matcher_version: Mapped[str] = mapped_column(String(32), nullable=False)
    classifier_version: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class MonthlyReportSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """每月一份冻结月报：报告原文、统计范围与规则版本一起留痕，复盘时不随数据变化。"""

    __tablename__ = "monthly_report_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "month", name="uq_monthly_report_snapshots_project_month"
        ),
        Index(
            "ix_monthly_report_snapshots_project_captured_at",
            "project_id",
            "captured_at",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 右开区间：period_end 是下月 1 日 00:00，不包含在报告月份内。
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    definitions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ReportShare(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """月报只读分享：只存令牌哈希，链接本身不落库；密码可选，可随时吊销。

    分享对象必须是冻结月报，不允许直接分享实时月报，避免客户看到的数字
    随后台数据变化而改变。白标字段只影响展示，不改变报告内容。
    """

    __tablename__ = "report_shares"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_report_shares_token_hash"),
        Index("ix_report_shares_project_snapshot", "project_id", "snapshot_id"),
        Index("ix_report_shares_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monthly_report_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    brand_name: Mapped[str | None] = mapped_column(String(80))
    brand_logo_url: Mapped[str | None] = mapped_column(String(500))
    accent_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#2563eb")
    contact_text: Mapped[str | None] = mapped_column(Text)
    show_leads: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    view_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


"""统计快照：每轮冻结一份不可变统计结果，防止历史趋势被配置变更重解释。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
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

"""预警规则与事件。

规则阈值存 JSONB，便于按项目调整；事件按 `(project_id, rule_id, dedupe_key)`
唯一，重复命中只更新 last_seen_at / trigger_count，不重复推送。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import AlertEventStatus, AlertRuleCode, AlertSeverity


class AlertRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_alert_rules_project_code"),
        Index("ix_alert_rules_project_enabled", "project_id", "is_enabled"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[AlertRuleCode] = mapped_column(
        str_enum(AlertRuleCode, "alert_rule_code"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        str_enum(AlertSeverity, "alert_severity"),
        nullable=False,
        default=AlertSeverity.WARNING,
        server_default=AlertSeverity.WARNING.value,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # 例：{"window_days": 7, "min_samples": 3, "drop_abs": 0.1}
    thresholds: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )


class AlertEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint("project_id", "rule_id", "dedupe_key", name="uq_alert_events_project_rule_dedupe"),
        Index("ix_alert_events_project_status", "project_id", "status"),
        Index("ix_alert_events_project_triggered", "project_id", "triggered_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[AlertRuleCode] = mapped_column(
        str_enum(AlertRuleCode, "alert_event_code"), nullable=False
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        str_enum(AlertSeverity, "alert_event_severity"), nullable=False
    )
    status: Mapped[AlertEventStatus] = mapped_column(
        str_enum(AlertEventStatus, "alert_event_status"),
        nullable=False,
        default=AlertEventStatus.OPEN,
        server_default=AlertEventStatus.OPEN.value,
    )
    dedupe_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Numeric(12, 6))
    baseline_value: Mapped[float | None] = mapped_column(Numeric(12, 6))
    current_samples: Mapped[int | None] = mapped_column(Integer)
    baseline_samples: Mapped[int | None] = mapped_column(Integer)
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    webhook_status: Mapped[str | None] = mapped_column(String(32))
    webhook_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

"""消耗计量账本：只记「用了多少」，不记「该收多少钱」。

设计边界（和计费系统划清）：

- **append-only**：一条消耗一行，不更新、不删除；重算靠事实表，不靠改写历史；
- **幂等**：`(project_id, metric, source_type, source_id)` 唯一，同一业务事实重跑不重复计数；
- **不存价格**：金额、套餐、账单一律不落这张表——要定价是另一件事，改这里就变成计费逻辑；
- 额度只用于提示，超出只警告不拦截。
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UsageMetric


class UsageEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一条消耗事实：某项目在某天，用掉了多少某个计量项。

    `source_type` + `source_id` 指回业务行（如 `monitoring_execution_attempt` + 尝试 id），
    用于幂等与「页面数字点回明细」。`organization_id` 冗余存一份，客户级汇总不必再 join 项目。
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "metric",
            "source_type",
            "source_id",
            name="uq_usage_events_project_metric_source",
        ),
        Index("ix_usage_events_project_day", "project_id", "occurred_on"),
        Index("ix_usage_events_org_metric_day", "organization_id", "metric", "occurred_on"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # 明细索引：引擎 code、渠道 code、导出类型等，用于按引擎核价/按类型拆账。
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    @property
    def metric_value(self) -> UsageMetric:
        return UsageMetric(self.metric)

"""项目级口径配置：通用默认 + 项目覆盖。

为什么要有这张表：窗口月数、连续采集目标、共识阈值、质量检查级别、SEO 必备标签
这些「口径」原本写死在代码常量里——换一个项目、换一个客户就得改代码。这里把它们
变成项目级配置：**默认值通用（谁都能跑），需要时按项目覆盖（各家口径不同）**。

纪律：
- 只允许白名单键，值类型按默认值校验，避免把任意 JSON 塞进来；
- 读配置走 `policy_value`，缺行即回默认，不产生隐式状态；
- 写入落审计，并记 note（为什么改口径）。
"""

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_project_policies_project_key"),
        Index("ix_project_policies_project_key", "project_id", "key"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

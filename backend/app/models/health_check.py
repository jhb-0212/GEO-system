"""B5 体检引擎：一次体检 = 一组「单项达成率」，不合成总分。

为什么不出总分（这是本模块唯一的口径边界，改代码前先看这段）：

- 12 项的分母互不相同：有的是「必填段数 6」，有的是「近 30 天有效样本」，有的是
  「渠道条数」。把「6 段里填了 0 段」和「923 条引用里复核了 412 条」加权成一个
  百分制，权重谁定、调一次权重历史就不可比；
- 平台的体检表本身就是逐项打钩，运营看的是「哪一项没做」，不是「我得了 63 分」。
  所以这里只存每一项的分子/分母/目标/结论，顶层只给「通过几项、未达成几项、
  无法计算几项」的计数，不给分数。

存库而不是每次现算，是为了能看「上次体检到这次体检，哪几项从 fail 变 pass」，
也为了让报告能引用某一次体检的固定快照（历史可比）。
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import HealthCheckStatus


class HealthCheckRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一次体检：项目级，可多次跑，每次留一份快照。"""

    __tablename__ = "health_check_runs"
    __table_args__ = (
        Index("ix_health_check_runs_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    # 规则表版本：改规则要在代码里升版本号，否则新旧两次体检的项数对不上
    ruleset_version: Mapped[str] = mapped_column(String(16), nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    passed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unknown_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class HealthCheckItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """单项结论：分子/分母/目标原样存，结论由三者直接决定，不再二次加工。"""

    __tablename__ = "health_check_items"
    __table_args__ = (
        Index("ix_health_check_items_run_order", "run_id", "sort_order"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("health_check_runs.id", ondelete="CASCADE"), nullable=False
    )
    check_key: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    numerator: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    denominator: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unit: Mapped[str] = mapped_column(String(8), nullable=False, default="条", server_default="条")
    # 目标达成率（百分数整数）。计数型规则的 denominator 就是目标条数，这里仍写 100
    target_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    status: Mapped[HealthCheckStatus] = mapped_column(
        str_enum(HealthCheckStatus, "health_check_status"), nullable=False
    )
    hint: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

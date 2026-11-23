"""原始回答快照：把「当时 AI 到底说了什么」钉成不可变证据。

为什么要单独一张表，而不是直接读 `monitoring_samples.raw_answer`：

1. `monitoring_samples` 的 `raw_response` / `raw_answer` 是活动数据，后续导入、清洗、重判都可能
   改写它；一旦改写，引用与形态的判定就失去可追溯的原始依据。
2. 快照是**追加一次、永不更新**的：`payload` 存当时的回答、引用清单与题目/引擎上下文，
   `content_hash` 与 `answer_hash` 分别钉住整包与纯回答文本。后续任何漂移都能被比对出来。
3. 快照不参与任何指标计算，只用于复核、离线重跑形态/引用抽取、以及争议时举证。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class AnswerSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一条样本的原始回答存档（每样本至多一份，重复存档返回既有记录）。"""

    __tablename__ = "answer_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "sample_id", name="uq_answer_snapshots_project_sample"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_samples.id", ondelete="CASCADE"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    answer_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

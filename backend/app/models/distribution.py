"""投喂批次：把一批已审核内容指向目标 AI 平台，进投喂前先过预检。

设计边界：
- 批次不复制内容正文，只记 content_version 引用；
- 预检结果随批次落库（`precheck`），但页面展示以「重新预检」的最新结果为准；
- 预检不过一律 blocked，不允许直接标记已投喂——避免把关口写在人脑里；
- **批次是计划，任务是执行**：确认投喂时按「内容版本 × 目标渠道」生成 `PublishTask`，
  批次自身不宣称「已发布」。只有回执才等于发出去了（见 `services/distribution_dispatch.py`）。
- 确认时冻结 `approval_snapshot`（渠道准入 + 发布账号 + 内容版本 + 预检哈希），
  一次写入不更新：三天后渠道被撤准入，也能解释当时为什么放行。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import DistributionBatchStatus, PushStatus, PushTargetType


class DistributionBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "distribution_batches"
    __table_args__ = (
        Index("ix_distribution_batches_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[DistributionBatchStatus] = mapped_column(
        str_enum(DistributionBatchStatus, "distribution_batch_status"),
        nullable=False,
        default=DistributionBatchStatus.BLOCKED,
        server_default=DistributionBatchStatus.BLOCKED.value,
    )
    # 投喂目标只能是渠道（头条/知乎/公众号），不再写引擎：
    # 内容投给渠道，被哪个引擎引用是「结果」，用 expected_engines 表达期望而非目标。
    target_channel_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    expected_engines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    precheck: Mapped[dict | None] = mapped_column(JSONB)
    # 确认投喂时冻结的准入证据：渠道准入状态、发布账号、内容版本、预检哈希。
    # 一次写入不更新，用于事后解释「当时凭什么放行」。
    approval_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    # 本批次实际生成的发布任务数（幂等复用也算在内），0 表示还没确认或没有可发内容。
    task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DistributionBatchItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "distribution_batch_items"

    # 明细也带 project_id：schema 约定所有业务表都按项目可直接过滤，
    # 不必再经 batch 表 join 一次才能落到项目范围。
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("distribution_batches.id", ondelete="CASCADE"), nullable=False
    )
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)


class DistributionPush(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """事实 → EEAT 信源的推送记录（G9）。

    边界：
    - 只允许推送**已核准**事实（护栏在 `services/fact_push.py`，不在这里）；
    - 百科方向只生成草稿词条，不代第三方平台发布；
    - 同 `(fact, target_type, target_ref)` 唯一，重复请求复用记录而不重复外发。
    """

    __tablename__ = "distribution_pushes"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "fact_id",
            "target_type",
            "target_ref",
            name="uq_distribution_pushes_fact_target",
        ),
        UniqueConstraint("project_id", "idempotency_key", name="uq_distribution_pushes_idem"),
        Index("ix_distribution_pushes_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    fact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("facts.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[PushTargetType] = mapped_column(
        str_enum(PushTargetType, "push_target_type"), nullable=False
    )
    # 百科方向存平台名（other / baidu_baike…），webhook 方向存目标 URL；空串而非 NULL，
    # 否则唯一约束在 NULL 上不生效，会重复建记录。
    target_ref: Mapped[str] = mapped_column(String(1024), nullable=False, default="", server_default="")
    status: Mapped[PushStatus] = mapped_column(
        str_enum(PushStatus, "push_status"),
        nullable=False,
        default=PushStatus.PENDING,
        server_default=PushStatus.PENDING.value,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 百科方向存生成的词条 id，webhook 方向存对方返回的状态码
    external_ref: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

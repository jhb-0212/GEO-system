"""权威事实库与回答事实核验。

设计口径：
- facts 是当前可引用的事实记录，同一项目同一 fact_type + fact_key 只有一条；
- 每次创建/修订/提交/审批/过期都追加一条 fact_versions 快照，历史不可改；
- answer_fact_claims 与品牌识别分开：品牌识别回答“有没有提到”，事实核验回答“说对了没有”；
- 错误/过期 claim 自动生成 correction_tasks，落到内容机会中心。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import (
    CorrectionTaskStatus,
    FactClaimVerdict,
    FactStatus,
    FactType,
    FactVersionAction,
)


class Fact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一条当前事实：修改走版本号递增和快照，不覆盖历史。"""

    __tablename__ = "facts"
    __table_args__ = (
        UniqueConstraint("project_id", "fact_type", "fact_key", name="uq_facts_project_type_key"),
        UniqueConstraint("project_id", "id", name="uq_facts_project_id_id"),
        Index("ix_facts_project_type_status", "project_id", "fact_type", "approval_status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    fact_type: Mapped[FactType] = mapped_column(
        str_enum(FactType, "fact_type"), nullable=False
    )
    fact_key: Mapped[str] = mapped_column(String(128), nullable=False)
    fact_value: Mapped[str] = mapped_column(Text, nullable=False)
    source_document: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    owner: Mapped[str | None] = mapped_column(String(128))
    approval_status: Mapped[FactStatus] = mapped_column(
        str_enum(FactStatus, "fact_status"),
        nullable=False,
        default=FactStatus.DRAFT,
        server_default=FactStatus.DRAFT.value,
    )
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facts.id", ondelete="SET NULL"))
    # “保证就业”类表述必须由业务方书面确认，approval 时强校验
    business_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    business_confirmed_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_note: Mapped[str | None] = mapped_column(Text)


class FactVersion(UUIDPrimaryKeyMixin, Base):
    """事实变更快照：完整前后 JSON，审批留痕，不可覆盖。"""

    __tablename__ = "fact_versions"
    __table_args__ = (
        UniqueConstraint("fact_id", "version_no", name="uq_fact_versions_fact_version"),
        Index("ix_fact_versions_project_fact", "project_id", "fact_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    fact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("facts.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[FactVersionAction] = mapped_column(
        str_enum(FactVersionAction, "fact_version_action"), nullable=False
    )
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    previous_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    change_note: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CorrectionTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """事实纠错任务：错误/过期 claim 自动生成，落到内容机会中心。"""

    __tablename__ = "correction_tasks"
    __table_args__ = (
        Index("ix_correction_tasks_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("answer_fact_claims.id", ondelete="SET NULL", use_alter=True, name="fk_correction_tasks_claim")
    )
    fact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facts.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[CorrectionTaskStatus] = mapped_column(
        str_enum(CorrectionTaskStatus, "correction_task_status"),
        nullable=False,
        default=CorrectionTaskStatus.OPEN,
        server_default=CorrectionTaskStatus.OPEN.value,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnswerFactClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一条 AI 回答中的事实陈述，人工判定与事实库是否一致。"""

    __tablename__ = "answer_fact_claims"
    __table_args__ = (
        Index("ix_answer_fact_claims_project_sample", "project_id", "sample_id"),
        Index("ix_answer_fact_claims_project_verdict", "project_id", "verdict"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_samples.id", ondelete="CASCADE"), nullable=False
    )
    citation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("monitoring_citations.id", ondelete="SET NULL")
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    fact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facts.id", ondelete="SET NULL"))
    verdict: Mapped[FactClaimVerdict | None] = mapped_column(
        str_enum(FactClaimVerdict, "fact_claim_verdict")
    )
    source_url: Mapped[str | None] = mapped_column(String(1024))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correction_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("correction_tasks.id", ondelete="SET NULL", use_alter=True, name="fk_answer_fact_claims_correction")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

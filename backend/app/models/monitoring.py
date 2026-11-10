"""GEO 监测：轮次 → 任务 → 采样 → 引用证据 → 证据文件。

唯一键：轮次 + 问题版本 + 引擎入口 + 采样序号（自然唯一，防重复建任务）。
样本状态机：pending → running → hit / miss / failed / manual_review。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import (
    CitationReviewStatus,
    EvidenceFileType,
    FailureCode,
    ReviewResult,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)


class MonitoringRound(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """采样轮次：首轮为基线，后续按同题同引擎同模式复测。"""

    __tablename__ = "monitoring_rounds"
    __table_args__ = (
        UniqueConstraint("project_id", "seq", name="uq_monitoring_rounds_project_seq"),
        Index("ix_monitoring_rounds_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[RoundStatus] = mapped_column(
        str_enum(RoundStatus, "round_status"),
        nullable=False,
        default=RoundStatus.PLANNING,
        server_default=RoundStatus.PLANNING.value,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class MonitoringTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一个测试组合：某轮次 × 某问题版本 × 某引擎入口 × 采样序号。"""

    __tablename__ = "monitoring_tasks"
    __table_args__ = (
        UniqueConstraint(
            "round_id",
            "question_version_id",
            "engine_entry_id",
            "sampling_no",
            name="uq_monitoring_tasks_round_question_entry_sampling",
        ),
        Index("ix_monitoring_tasks_project_status", "project_id", "status"),
        Index("ix_monitoring_tasks_project_round_status", "project_id", "round_id", "status"),
        Index("ix_monitoring_tasks_round", "round_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    round_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_rounds.id", ondelete="RESTRICT"), nullable=False
    )
    question_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), nullable=False
    )
    engine_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_engine_entries.id", ondelete="RESTRICT"), nullable=False
    )
    sampling_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sampling_mode: Mapped[SamplingMode] = mapped_column(
        str_enum(SamplingMode, "sampling_mode"),
        nullable=False,
        default=SamplingMode.SEARCH_ON,
    )
    status: Mapped[TaskStatus] = mapped_column(
        str_enum(TaskStatus, "task_status"),
        nullable=False,
        default=TaskStatus.PENDING,
        server_default=TaskStatus.PENDING.value,
    )
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class MonitoringSample(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一次实际执行的结果：原始回答、品牌识别、状态与失败原因都在这里。"""

    __tablename__ = "monitoring_samples"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uq_monitoring_samples_task_attempt"),
        Index("ix_monitoring_samples_project_status", "project_id", "status"),
        Index("ix_monitoring_samples_project_sampled_at", "project_id", "sampled_at"),
        Index("ix_monitoring_samples_task_status", "task_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    status: Mapped[SampleStatus] = mapped_column(
        str_enum(SampleStatus, "sample_status"),
        nullable=False,
        default=SampleStatus.PENDING,
        server_default=SampleStatus.PENDING.value,
    )
    sampled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sampling_mode: Mapped[SamplingMode] = mapped_column(
        str_enum(SamplingMode, "sample_sampling_mode"),
        nullable=False,
        default=SamplingMode.SEARCH_ON,
    )

    raw_answer: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    brand_mentioned: Mapped[bool | None] = mapped_column(Boolean)

    failure_code: Mapped[FailureCode | None] = mapped_column(str_enum(FailureCode, "failure_code"))
    failure_note: Mapped[str | None] = mapped_column(Text)

    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_result: Mapped[ReviewResult | None] = mapped_column(str_enum(ReviewResult, "review_result"))
    review_note: Mapped[str | None] = mapped_column(Text)


class MonitoringCitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """引用证据：原始 URL、归一化 URL、域名、渠道归属与人工复核结果分开保存。"""

    __tablename__ = "monitoring_citations"
    __table_args__ = (
        Index("ix_monitoring_citations_project_sample", "project_id", "sample_id"),
        Index("ix_monitoring_citations_project_domain_review", "project_id", "domain", "review_status"),
        Index("ix_monitoring_citations_channel", "channel_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_samples.id", ondelete="CASCADE"), nullable=False
    )
    raw_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(255))
    channel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    is_brand_related: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    review_status: Mapped[CitationReviewStatus] = mapped_column(
        str_enum(CitationReviewStatus, "citation_review_status"),
        nullable=False,
        default=CitationReviewStatus.AUTO,
        server_default=CitationReviewStatus.AUTO.value,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)


class EvidenceFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """证据文件元信息：文件本体放对象存储，库里只存 key 与校验值。"""

    __tablename__ = "evidence_files"
    __table_args__ = (Index("ix_evidence_files_project_sample", "project_id", "sample_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    sample_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("monitoring_samples.id", ondelete="CASCADE")
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[EvidenceFileType] = mapped_column(
        str_enum(EvidenceFileType, "evidence_file_type"), nullable=False
    )
    checksum: Mapped[str | None] = mapped_column(String(128))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(String(128))

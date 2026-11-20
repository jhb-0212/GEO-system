"""GEO 监测：轮次 → 任务 → 采样 → 引用证据 → 证据文件。

唯一键：轮次 + 问题版本 + 引擎入口 + 采样序号（自然唯一，防重复建任务）。
样本状态机：pending → running → hit / miss / no_answer_surface / failed / manual_review。
轮次进入执行前固定测量快照（品牌词表、竞品、识别规则版本），
同一轮内所有任务只读快照，中途修改品牌配置只影响下一轮。
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import (
    AnswerKind,
    AttemptStatus,
    CitationPageType,
    CitationReviewStatus,
    CitationUsage,
    ClassificationSource,
    EvidenceFileType,
    FailureCode,
    ReviewResult,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    SourceCategory,
    SourceReviewStatus,
    TaskStatus,
)


class MonitoringRound(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """采样轮次：基线由 is_baseline 标记，不必是首轮；后续按同题同引擎同模式复测。"""

    __tablename__ = "monitoring_rounds"
    __table_args__ = (
        UniqueConstraint("project_id", "seq", name="uq_monitoring_rounds_project_seq"),
        UniqueConstraint("project_id", "id", name="uq_monitoring_rounds_project_id_id"),
        Index(
            "uq_monitoring_rounds_project_baseline",
            "project_id",
            unique=True,
            postgresql_where=text("is_baseline IS TRUE"),
        ),
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
    # 测量快照：轮次创建时固定品牌词表/竞品/识别与归一化规则版本。
    # 执行只读快照，不读当前 BrandProfile；修改配置只影响下一轮。
    analysis_config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    analysis_config_hash: Mapped[str | None] = mapped_column(String(64))
    analysis_config_version: Mapped[str | None] = mapped_column(String(32))
    analysis_config_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Competitor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """项目内竞品实体：用于答案提及归因与 Share of Voice，不把竞品名写进自由文本。"""

    __tablename__ = "competitors"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_competitors_project_name"),
        Index("ix_competitors_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    notes: Mapped[str | None] = mapped_column(Text)


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
        UniqueConstraint("project_id", "id", name="uq_monitoring_tasks_project_id_id"),
        ForeignKeyConstraint(
            ["project_id", "round_id"],
            ["monitoring_rounds.project_id", "monitoring_rounds.id"],
            name="fk_monitoring_tasks_project_round",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "question_version_id"],
            ["question_versions.project_id", "question_versions.id"],
            name="fk_monitoring_tasks_project_question_version",
            ondelete="RESTRICT",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    serial_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        server_default=text("nextval('monitoring_tasks_serial_no_seq')"),
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
    # 一次任务的所有样本/引用共享同一个 trace_id，用于串起轮次→任务→样本→引用
    trace_id: Mapped[str | None] = mapped_column(String(32), index=True)
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
    # 执行租约：worker 领取任务时写入，落终态时清空；过期由调度器回收
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MonitoringExecutionAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """每一次任务执行尝试：领取、发起请求、落库各自留痕，不与样本 attempt_no 混同。

    状态用途：
    - claimed：已领取但未发请求，租约过期可安全重排；
    - dispatching：请求已发出，租约过期只能判 uncertain，禁止自动重发；
    - rate_limited：本地限流拒绝，没有调用外部平台，也不占平台额度。
    """

    __tablename__ = "monitoring_execution_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uq_monitoring_attempts_task_attempt"),
        Index("ix_monitoring_attempts_status_lease", "status", "lease_expires_at"),
        Index("ix_monitoring_attempts_project_task", "project_id", "task_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    worker_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(
        str_enum(AttemptStatus, "attempt_status"),
        nullable=False,
        default=AttemptStatus.CLAIMED,
        server_default=AttemptStatus.CLAIMED.value,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[FailureCode | None] = mapped_column(
        str_enum(FailureCode, "attempt_failure_code")
    )
    note: Mapped[str | None] = mapped_column(Text)


class MonitoringSample(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一次实际执行的结果：原始回答、品牌识别、状态与失败原因都在这里。"""

    __tablename__ = "monitoring_samples"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uq_monitoring_samples_task_attempt"),
        UniqueConstraint(
            "project_id",
            "conversation_id",
            name="uq_monitoring_samples_project_conversation",
        ),
        Index("ix_monitoring_samples_project_status", "project_id", "status"),
        Index("ix_monitoring_samples_project_sampled_at", "project_id", "sampled_at"),
        Index("ix_monitoring_samples_task_status", "task_id", "status"),
        Index(
            "ix_monitoring_samples_project_engine_model_sampled_at",
            "project_id",
            "engine_model",
            "sampled_at",
        ),
        Index(
            "ix_monitoring_samples_project_country_sampled_at",
            "project_id",
            "country_code",
            "sampled_at",
        ),
        UniqueConstraint("project_id", "id", name="uq_monitoring_samples_project_id_id"),
        ForeignKeyConstraint(
            ["project_id", "task_id"],
            ["monitoring_tasks.project_id", "monitoring_tasks.id"],
            name="fk_monitoring_samples_project_task",
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    serial_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        server_default=text("nextval('monitoring_samples_serial_no_seq')"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    trace_id: Mapped[str | None] = mapped_column(String(32), index=True)

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
    # 每个样本对应一次独立会话：API 入口为无状态请求，网页端为新建对话，手测为人工录入。
    # conversation_id 由系统生成并在项目内唯一，直接证明没有跨题复用会话。
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=lambda: uuid.uuid4().hex,
    )
    conversation_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="stateless",
        server_default="stateless",
    )

    raw_answer: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # 网关留存：原始请求体（不含 Authorization）、耗时、token 与可选估算费用
    request_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_cny: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    gateway_version: Mapped[str | None] = mapped_column(String(32))
    # 严格口径：答案里点名提到品牌（正式名或别名）才算 True。
    brand_mentioned: Mapped[bool | None] = mapped_column(Boolean)
    # 宽松口径：答案没点名，但给出了能唯一定位品牌的标识（地址、电话、公众号名）。
    # 与 brand_mentioned 并行存在、互不覆盖：前者是跨引擎可比指标，后者衡量「可识别」。
    brand_identified: Mapped[bool | None] = mapped_column(Boolean)

    # 统一匹配证据：谁命中、命中在哪、原文片段、列表位次与规则版本。
    # 只记录判定依据，不改变提及/可识别两个布尔口径。
    brand_match_kind: Mapped[str | None] = mapped_column(String(16))
    brand_match_term: Mapped[str | None] = mapped_column(String(128))
    brand_match_offset: Mapped[int | None] = mapped_column(Integer)
    brand_match_offset_end: Mapped[int | None] = mapped_column(Integer)
    brand_match_evidence: Mapped[str | None] = mapped_column(Text)
    brand_list_rank: Mapped[int | None] = mapped_column(Integer)
    matcher_version: Mapped[str | None] = mapped_column(String(32))

    # 答案口径：生成回答(answer) vs 检索结果(search_result)。两类样本的提及率/引用率
    # 不得合并统计；NULL 表示未声明（执行前占位样本），统计时按 answer 兜底。
    answer_kind: Mapped[AnswerKind | None] = mapped_column(str_enum(AnswerKind, "answer_kind"))

    # 引擎/地域/语言快照：同一条引擎入口在不同时间可能换模型，不能只依赖目录表
    engine_model: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    country_code: Mapped[str | None] = mapped_column(String(8))
    language: Mapped[str | None] = mapped_column(String(16))

    # 分析版本戳：这条样本是用哪一版识别规则/词表算出来的；规则升级后可据此
    # 区分"旧分析"与"新分析"，不覆盖原始回答事实。
    analysis_version: Mapped[str | None] = mapped_column(String(32))
    analysis_config_hash: Mapped[str | None] = mapped_column(String(64))
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
        Index("ix_monitoring_citations_project_page_type", "project_id", "page_type"),
        Index(
            "ix_monitoring_citations_project_source_category",
            "project_id",
            "source_category",
        ),
        Index(
            "ix_monitoring_citations_project_usage_domain",
            "project_id",
            "citation_usage",
            "domain",
        ),
        Index("ix_monitoring_citations_project_competitor", "project_id", "competitor_id"),
        UniqueConstraint("project_id", "id", name="uq_monitoring_citations_project_id_id"),
        ForeignKeyConstraint(
            ["project_id", "sample_id"],
            ["monitoring_samples.project_id", "monitoring_samples.id"],
            name="fk_monitoring_citations_project_sample",
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_samples.id", ondelete="CASCADE"), nullable=False
    )
    trace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    raw_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(Text)
    # 引用在回答中的原始顺序；1 为第一条，仅保存 provider 明确给出的顺序或解析顺序
    position: Mapped[int | None] = mapped_column(Integer)
    citation_order: Mapped[int | None] = mapped_column(Integer)
    provider_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parse_version: Mapped[str | None] = mapped_column(String(32))
    is_domain_level: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    source_category: Mapped[SourceCategory] = mapped_column(
        str_enum(SourceCategory, "citation_source_category"),
        nullable=False,
        default=SourceCategory.UNKNOWN,
        server_default=SourceCategory.UNKNOWN.value,
    )
    page_type: Mapped[CitationPageType] = mapped_column(
        str_enum(CitationPageType, "citation_page_type"),
        nullable=False,
        default=CitationPageType.OTHER,
        server_default=CitationPageType.OTHER.value,
    )
    source_category_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    page_type_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    classification_source: Mapped[ClassificationSource | None] = mapped_column(
        str_enum(ClassificationSource, "citation_classification_source")
    )
    classification_rule_version: Mapped[str | None] = mapped_column(String(32))
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification_reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    classification_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification_note: Mapped[str | None] = mapped_column(Text)
    # provider 原始字段原样留痕，便于规则升级后复核，不把推断写进 raw_url
    provider_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    is_brand_related: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    citation_usage: Mapped[CitationUsage | None] = mapped_column(
        str_enum(CitationUsage, "citation_usage")
    )
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competitors.id", ondelete="SET NULL")
    )

    review_status: Mapped[CitationReviewStatus] = mapped_column(
        str_enum(CitationReviewStatus, "citation_review_status"),
        nullable=False,
        default=CitationReviewStatus.AUTO,
        server_default=CitationReviewStatus.AUTO.value,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)


class CitationSourceReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """未知被引域名审核队列：只做来源分类，不自动创建发布渠道。

    人工分类后 `classification_source=manual`，后续自动分类不得覆盖；
    `page_type` 留在每条 citation 上，因为同站不同页可以是不同页型。
    """

    __tablename__ = "citation_source_reviews"
    __table_args__ = (
        UniqueConstraint("project_id", "domain", name="uq_citation_source_reviews_project_domain"),
        Index("ix_citation_source_reviews_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SourceReviewStatus] = mapped_column(
        str_enum(SourceReviewStatus, "source_review_status"),
        nullable=False,
        default=SourceReviewStatus.PENDING,
        server_default=SourceReviewStatus.PENDING.value,
    )
    source_category: Mapped[SourceCategory | None] = mapped_column(
        str_enum(SourceCategory, "source_review_category")
    )
    suggested_source_category: Mapped[SourceCategory | None] = mapped_column(
        str_enum(SourceCategory, "source_review_suggested_category")
    )
    classification_source: Mapped[ClassificationSource | None] = mapped_column(
        str_enum(ClassificationSource, "source_review_classification_source")
    )
    classification_rule_version: Mapped[str | None] = mapped_column(String(32))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)


class MonitoringCompetitorMention(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """竞品提及：一次回答可提及多个竞品，按样本+竞品唯一，用于 Share of Voice 计数。"""

    __tablename__ = "monitoring_competitor_mentions"
    __table_args__ = (
        UniqueConstraint(
            "sample_id",
            "competitor_id",
            name="uq_monitoring_competitor_mentions_sample_competitor",
        ),
        Index(
            "ix_monitoring_competitor_mentions_project_competitor",
            "project_id",
            "competitor_id",
        ),
        Index("ix_monitoring_competitor_mentions_project_sample", "project_id", "sample_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_samples.id", ondelete="CASCADE"), nullable=False
    )
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int | None] = mapped_column(Integer)
    evidence_text: Mapped[str | None] = mapped_column(Text)


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


class MonitoringBrandMention(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """品牌提及明细的旧版留档表：保留历史数据，当前统计以样本上的聚合字段为准。"""

    __tablename__ = "monitoring_brand_mentions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "sample_id",
            "term",
            "offset_start",
            name="uq_monitoring_brand_mentions_sample_term_offset",
        ),
        Index("ix_monitoring_brand_mentions_project_sample", "project_id", "sample_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_samples.id", ondelete="CASCADE"), nullable=False
    )
    brand_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("brand_profiles.id", ondelete="SET NULL")
    )
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    term_type: Mapped[str] = mapped_column(String(32), nullable=False)
    offset_start: Mapped[int] = mapped_column(Integer, nullable=False)
    offset_end: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    sentence: Mapped[str | None] = mapped_column(Text)
    list_rank: Mapped[int | None] = mapped_column(Integer)
    requires_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    matcher_version: Mapped[str] = mapped_column(String(32), nullable=False)


class MonitoringSourceProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """域名来源人工分类的旧版表：保留结构，供历史数据查询与迁移核对。"""

    __tablename__ = "monitoring_source_profiles"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "domain", name="uq_monitoring_source_profiles_project_domain"
        ),
        Index(
            "ix_monitoring_source_profiles_project_domain",
            "project_id",
            "domain",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    source_category: Mapped[SourceCategory] = mapped_column(
        str_enum(SourceCategory, "monitoring_source_profile_source_category"),
        nullable=False,
    )
    suggested_source_category: Mapped[SourceCategory | None] = mapped_column(
        str_enum(SourceCategory, "monitoring_source_profile_suggested_category")
    )
    classification_rule_version: Mapped[str | None] = mapped_column(String(32))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

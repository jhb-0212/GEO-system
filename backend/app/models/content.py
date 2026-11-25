"""内容与版本：母稿/渠道稿分离，版本不可覆盖，审批留哈希快照，运营计划与排期挂在这里。"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import (
    BudgetApprovalStatus,
    BudgetCategory,
    ContentKind,
    ContentFormat,
    ContentPlanStatus,
    ContentStatus,
    PagePublishStatus,
    PageType,
    PlanType,
    QuoteStatus,
    ReviewDecision,
)


class ContentItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """内容实体：kind=master 为母稿，kind=channel 为渠道稿且必须指向母稿与渠道。"""

    __tablename__ = "content_items"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'master' AND parent_id IS NULL AND channel_id IS NULL) OR "
            "(kind = 'channel' AND (status = 'archived' OR "
            "(parent_id IS NOT NULL AND channel_id IS NOT NULL)))",
            name="content_links",
        ),
        Index("ix_content_items_project_kind_status", "project_id", "kind", "status"),
        Index("ix_content_items_parent", "parent_id"),
        Index("ix_content_items_channel", "channel_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="RESTRICT")
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    kind: Mapped[ContentKind] = mapped_column(str_enum(ContentKind, "content_kind"), nullable=False)
    content_type: Mapped[ContentFormat | None] = mapped_column(
        str_enum(ContentFormat, "content_format")
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus, "content_status"),
        nullable=False,
        default=ContentStatus.DRAFT,
        server_default=ContentStatus.DRAFT.value,
    )
    # 指向当前生效版本；用 use_alter 打散与 content_versions 的循环外键
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "content_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_content_items_current_version",
        )
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )


class ContentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """内容版本：正文 + 哈希 + 审核状态，创建后不得覆盖。"""

    __tablename__ = "content_versions"
    __table_args__ = (
        UniqueConstraint("item_id", "version_no", name="uq_content_versions_item_version"),
        UniqueConstraint("project_id", "id", name="uq_content_versions_project_id_id"),
        Index("ix_content_versions_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus, "content_version_status"),
        nullable=False,
        default=ContentStatus.DRAFT,
        server_default=ContentStatus.DRAFT.value,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )


class ContentVersionQuestion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "content_version_questions"
    __table_args__ = (
        UniqueConstraint("version_id", "question_id", name="uq_content_version_questions_version_question"),
        ForeignKeyConstraint(
            ["project_id", "version_id"],
            ["content_versions.project_id", "content_versions.id"],
            name="fk_content_version_questions_project_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "question_id"],
            ["questions.project_id", "questions.id"],
            name="fk_content_version_questions_project_question",
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )


class ContentVersionKeyword(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "content_version_keywords"
    __table_args__ = (
        UniqueConstraint("version_id", "keyword_id", name="uq_content_version_keywords_version_keyword"),
        ForeignKeyConstraint(
            ["project_id", "version_id"],
            ["content_versions.project_id", "content_versions.id"],
            name="fk_content_version_keywords_project_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "keyword_id"],
            ["keywords.project_id", "keywords.id"],
            name="fk_content_version_keywords_project_keyword",
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=False
    )
    keyword_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False
    )


class ContentVersionCitation(UUIDPrimaryKeyMixin, Base):
    """内容版本引用的监测证据，保证内容与证据可双向追溯。"""

    __tablename__ = "content_version_citations"
    __table_args__ = (
        UniqueConstraint("version_id", "citation_id", name="uq_content_version_citations_version_citation"),
        ForeignKeyConstraint(
            ["project_id", "version_id"],
            ["content_versions.project_id", "content_versions.id"],
            name="fk_content_version_citations_project_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "citation_id"],
            ["monitoring_citations.project_id", "monitoring_citations.id"],
            name="fk_content_version_citations_project_citation",
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=False
    )
    citation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_citations.id", ondelete="CASCADE"), nullable=False
    )


class ContentVersionFact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """内容版本引用的权威事实；记录关联时的版本号，事实修订后审批必须重确认。"""

    __tablename__ = "content_version_facts"
    __table_args__ = (
        UniqueConstraint("version_id", "fact_id", name="uq_content_version_facts_version_fact"),
        ForeignKeyConstraint(
            ["project_id", "version_id"],
            ["content_versions.project_id", "content_versions.id"],
            name="fk_content_version_facts_project_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "fact_id"],
            ["facts.project_id", "facts.id"],
            name="fk_content_version_facts_project_fact",
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=False
    )
    fact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("facts.id", ondelete="CASCADE"), nullable=False
    )
    # 关联时的内容版本号；事实后续修订（version_no 增加）时，审批必须重新确认新值
    fact_version_no: Mapped[int] = mapped_column(Integer, nullable=False)


class ContentReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """审批记录：审批人、时间、意见 + 审批时的内容哈希快照。"""

    __tablename__ = "content_reviews"
    __table_args__ = (
        Index("ix_content_reviews_project_version", "project_id", "version_id"),
        Index("ix_content_reviews_reviewer", "reviewer_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    decision: Mapped[ReviewDecision] = mapped_column(
        str_enum(ReviewDecision, "review_decision"), nullable=False
    )
    comment: Mapped[str | None] = mapped_column(Text)
    content_hash_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)


class PublicPage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """公开品牌站事实页：稳定独立 URL，canonical 与发布状态在此登记。"""

    __tablename__ = "public_pages"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_public_pages_project_slug"),
        Index("ix_public_pages_project_status", "project_id", "publish_status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    page_type: Mapped[PageType] = mapped_column(str_enum(PageType, "page_type"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    publish_status: Mapped[PagePublishStatus] = mapped_column(
        str_enum(PagePublishStatus, "page_publish_status"),
        nullable=False,
        default=PagePublishStatus.DRAFT,
        server_default=PagePublishStatus.DRAFT.value,
    )
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="SET NULL")
    )
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # L1 技术可访问性检查；由手动或周期任务回填，不把检查结果混入发布状态。
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    in_sitemap: Mapped[bool | None] = mapped_column(Boolean)
    canonical_ok: Mapped[bool | None] = mapped_column(Boolean)
    http_status: Mapped[int | None] = mapped_column(Integer)
    js_dependent: Mapped[bool | None] = mapped_column(Boolean)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_error: Mapped[str | None] = mapped_column(Text)


class ContentPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """内容运营任务：选题 → 生产 → 排期，关联渠道、母稿与官网事实页。"""

    __tablename__ = "content_plans"
    __table_args__ = (
        Index("ix_content_plans_project_status_scheduled", "project_id", "status", "scheduled_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_type: Mapped[PlanType] = mapped_column(str_enum(PlanType, "plan_type"), nullable=False)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="SET NULL")
    )
    site_page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public_pages.id", ondelete="SET NULL")
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ContentPlanStatus] = mapped_column(
        str_enum(ContentPlanStatus, "content_plan_status"),
        nullable=False,
        default=ContentPlanStatus.PROPOSED,
        server_default=ContentPlanStatus.PROPOSED.value,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    # B7 新媒体发布记录：只记「是否已发布 + 发布链接 + 人工备注」，不自动采集播放数据。
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    publish_url: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    play_note: Mapped[str | None] = mapped_column(Text)


class MediaQuote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """媒体合作报价与审批：按实际选题与明确报价单独审批，预算=通过篇数×确认单价。"""

    __tablename__ = "media_quotes"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_media_quotes_project_id_id"),
        Index("ix_media_quotes_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_plans.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    status: Mapped[QuoteStatus] = mapped_column(
        str_enum(QuoteStatus, "quote_status"),
        nullable=False,
        default=QuoteStatus.PENDING,
        server_default=QuoteStatus.PENDING.value,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class BudgetApproval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """四类费用预算审批：开发工时、内容制作、媒体投放、监测服务。

    与 media_quotes 的分工：media_quotes 只表达“渠道 × 篇数 × 确认单价”的媒体报价；
    本表表达跨四类成本的统一申请与审批，不把开发工时和监测服务塞进内容计划。
    """

    __tablename__ = "budget_approvals"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="quantity_positive",
        ),
        CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0",
            name="unit_price_nonnegative",
        ),
        UniqueConstraint(
            "project_id", "id", name="uq_budget_approvals_project_id_id"
        ),
        ForeignKeyConstraint(
            ["project_id", "media_quote_id"],
            ["media_quotes.project_id", "media_quotes.id"],
            name="fk_budget_approvals_project_media_quote",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_budget_approvals_project_status_category",
            "project_id",
            "status",
            "category",
        ),
        Index("ix_budget_approvals_media_quote", "media_quote_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    # P76：媒体投放预算必须指向一条已批准的媒体报价，单价/币种以报价为准。
    media_quote_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_quotes.id", ondelete="RESTRICT")
    )
    category: Mapped[BudgetCategory] = mapped_column(
        str_enum(BudgetCategory, "budget_category"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit: Mapped[str | None] = mapped_column(String(32))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    status: Mapped[BudgetApprovalStatus] = mapped_column(
        str_enum(BudgetApprovalStatus, "budget_approval_status"),
        nullable=False,
        default=BudgetApprovalStatus.PENDING,
        server_default=BudgetApprovalStatus.PENDING.value,
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    decision_note: Mapped[str | None] = mapped_column(Text)

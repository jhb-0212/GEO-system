"""内容与版本：母稿/渠道稿分离，版本不可覆盖，审批留哈希快照，运营计划与排期挂在这里。"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import (
    ContentKind,
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


class MediaQuote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """媒体合作报价与审批：按实际选题与明确报价单独审批，预算=通过篇数×确认单价。"""

    __tablename__ = "media_quotes"
    __table_args__ = (Index("ix_media_quotes_project_status", "project_id", "status"),)

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

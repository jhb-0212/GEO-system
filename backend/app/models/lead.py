"""GEO 线索：轻量获客线索，与可追踪访问分开统计，不做完整 CRM。"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Identity, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import EnrollmentStatus


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_project_created", "project_id", "created_at"),
        Index("ix_leads_project_enrollment", "project_id", "enrollment_status"),
        Index("ix_leads_project_source_question", "project_id", "source_question_id"),
        Index("ix_leads_project_source_channel", "project_id", "source_channel_id"),
        Index("ix_leads_project_source_engine", "project_id", "source_engine_id"),
        Index("ix_leads_project_session", "project_id", "session_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    serial_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        server_default=text("nextval('leads_serial_no_seq')"),
    )
    lead_source: Mapped[str | None] = mapped_column(String(64))
    source_question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    source_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL")
    )
    source_engine_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_engines.id", ondelete="SET NULL")
    )
    landing_url: Mapped[str | None] = mapped_column(String(512))
    session_id: Mapped[str | None] = mapped_column(String(64))
    utm_campaign: Mapped[str | None] = mapped_column(String(128))
    reported_ai_product: Mapped[str | None] = mapped_column(String(64))
    interested_course: Mapped[str | None] = mapped_column(String(128))
    contact_name: Mapped[str | None] = mapped_column(String(64))
    contact_phone: Mapped[str | None] = mapped_column(String(64))
    contact_wechat: Mapped[str | None] = mapped_column(String(64))
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    enrollment_status: Mapped[EnrollmentStatus] = mapped_column(
        str_enum(EnrollmentStatus, "enrollment_status"),
        nullable=False,
        default=EnrollmentStatus.UNKNOWN,
        server_default=EnrollmentStatus.UNKNOWN.value,
    )
    note: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )
    # B4 获客：只存访客 IP 哈希 + 省市，不存 IP 原文；哈希用于同访客去重。
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    visitor_region: Mapped[str | None] = mapped_column(String(64))


class LeadMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """线索留言：访客留言与运营回复同表，author_role 区分；未读只对运营侧有意义。"""

    __tablename__ = "lead_messages"
    __table_args__ = (
        Index("ix_lead_messages_project_lead", "project_id", "lead_id", "created_at"),
        Index("ix_lead_messages_project_unread", "project_id", "is_read"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    # 同一事务里两条留言的 created_at 可能完全相同，用自增序号固定「谁先说」
    seq: Mapped[int] = mapped_column(Identity(), nullable=False)
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    author_role: Mapped[str] = mapped_column(String(16), nullable=False, default="visitor")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

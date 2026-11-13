"""GEO 线索：轻量招生线索，与可追踪访问分开统计，不做完整 CRM。"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
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
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
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

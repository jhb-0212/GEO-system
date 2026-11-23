"""FAQ 与素材库：项目内的运营内容，独立于监测样本与内容发布。"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import FaqStatus, MaterialCategory


class Faq(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "faqs"
    __table_args__ = (
        Index("ix_faqs_project_status", "project_id", "status"),
        Index("ix_faqs_project_category", "project_id", "category"),
        Index("ix_faqs_project_deleted", "project_id", "deleted_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    question: Mapped[str] = mapped_column(String(255), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[FaqStatus] = mapped_column(
        str_enum(FaqStatus, "faq_status"),
        nullable=False,
        default=FaqStatus.DRAFT,
        server_default=FaqStatus.DRAFT.value,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Material(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "materials"
    __table_args__ = (
        Index("ix_materials_project_category", "project_id", "category"),
        Index("ix_materials_project_group", "project_id", "group_name"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[MaterialCategory] = mapped_column(
        str_enum(MaterialCategory, "material_category"),
        nullable=False,
        default=MaterialCategory.DOCUMENT,
        server_default=MaterialCategory.DOCUMENT.value,
    )
    # 分组：同一批图/成片归到一个分组名下（如「校区环境」「2026 春招成片」）。
    # 不做层级树，一层分组足够覆盖门店图册与成片归档；排序只在组内生效。
    group_name: Mapped[str | None] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 来源：人工上传 / 门店采集 / 外部交付 等自由标签，仅用于筛选与追溯，不参与权限判定。
    source: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Certification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """项目资质：营业执照、办学许可、行业认证等，带有效期。

    到期状态不落库，读取时按 expires_on 现算——落库就要跑定时任务去刷新，
    这里只存事实，展示口径由接口统一给（valid / expiring / expired）。
    """

    __tablename__ = "certifications"
    __table_args__ = (
        Index("ix_certifications_project_active", "project_id", "is_active"),
        Index("ix_certifications_project_expires", "project_id", "expires_on"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    issuer: Mapped[str | None] = mapped_column(String(255))
    cert_no: Mapped[str | None] = mapped_column(String(128))
    issued_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    evidence_url: Mapped[str | None] = mapped_column(String(512))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

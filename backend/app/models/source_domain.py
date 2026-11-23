"""站点自证证据：给「待人工判」的域名存一份首页标题/描述。

为什么单独一张表：站点归类要人判，但人不该为了判一个域名去手动开浏览器。这里缓存
站点首页（根域）与一条被引页面的 `<title>` / `meta description`，作为判定依据；
**只存站点自己写的话，不存任何推断结论**，判定仍由人做。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class SourceDomainEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_domain_evidence"
    __table_args__ = (
        UniqueConstraint("project_id", "site", name="uq_source_domain_evidence_project_site"),
        Index("ix_source_domain_evidence_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    site: Mapped[str] = mapped_column(String(200), nullable=False)
    fetched_url: Mapped[str | None] = mapped_column(String(500))
    title: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    sample_url: Mapped[str | None] = mapped_column(String(500))
    sample_title: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    detail: Mapped[str | None] = mapped_column(String(120))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

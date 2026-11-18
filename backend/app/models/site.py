"""官网诊断与访问观测：把机器访问和人类访问分开记账。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class CrawlerEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """L2 实际抓取行为：官网/CDN 访问日志导入，每条一次请求。"""

    __tablename__ = "crawler_events"
    __table_args__ = (
        Index("ix_crawler_events_project_occurred", "project_id", "occurred_at"),
        Index("ix_crawler_events_project_bot", "project_id", "verified_bot"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    public_page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public_pages.id", ondelete="SET NULL")
    )
    page_url: Mapped[str] = mapped_column(Text, nullable=False)
    ua_claimed: Mapped[str | None] = mapped_column(String(512))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    # UA 只是声明；verified_bot 必须由导入方按官方 IP 段/反向 DNS 核验后回填。
    verified_bot: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    http_status: Mapped[int | None] = mapped_column(Integer)
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    import_source: Mapped[str | None] = mapped_column(String(64))


class TrafficEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """L3 用户访问事件：官网埋点或日志导入，只存匿名 session 与来源参数。"""

    __tablename__ = "traffic_events"
    __table_args__ = (
        Index("ix_traffic_events_project_occurred", "project_id", "occurred_at"),
        Index("ix_traffic_events_project_session", "project_id", "visitor_session_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    visitor_session_id: Mapped[str | None] = mapped_column(String(64))
    landing_url: Mapped[str] = mapped_column(Text, nullable=False)
    utm_source: Mapped[str | None] = mapped_column(String(128))
    utm_campaign: Mapped[str | None] = mapped_column(String(128))
    referrer: Mapped[str | None] = mapped_column(Text)
    is_bot: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    import_source: Mapped[str | None] = mapped_column(String(64))

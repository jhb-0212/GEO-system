"""媒体渠道适配器：不自建媒体池，只登记已合作供应商与订单。

供应商凭据不落库，只存环境变量名；订单按幂等键唯一，重试不会重复下单。
manual 适配器用于尚未提供 API 的渠道：报价人工确认，状态由运营回填。
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import MediaOrderStatus, MediaProviderAdapter


class MediaProvider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "media_providers"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_media_providers_project_code"),
        Index("ix_media_providers_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter: Mapped[MediaProviderAdapter] = mapped_column(
        str_enum(MediaProviderAdapter, "media_provider_adapter"), nullable=False
    )
    endpoint: Mapped[str | None] = mapped_column(String(500))
    # 只存环境变量名，例如 MEDIA_PROVIDER_X_TOKEN；不在库里存明文密钥。
    token_env: Mapped[str | None] = mapped_column(String(128))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_health: Mapped[str | None] = mapped_column(String(32))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "media_orders"
    __table_args__ = (
        UniqueConstraint("project_id", "provider_id", "idempotency_key", name="uq_media_orders_provider_idem"),
        Index("ix_media_orders_project_status", "project_id", "status"),
        Index("ix_media_orders_provider", "provider_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_providers.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    external_order_id: Mapped[str | None] = mapped_column(String(128))
    media_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    status: Mapped[MediaOrderStatus] = mapped_column(
        str_enum(MediaOrderStatus, "media_order_status"),
        nullable=False,
        default=MediaOrderStatus.DRAFT,
        server_default=MediaOrderStatus.DRAFT.value,
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_url: Mapped[str | None] = mapped_column(String(500))

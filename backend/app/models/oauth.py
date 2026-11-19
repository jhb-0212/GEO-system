"""平台 OAuth 授权：连接状态与一次性授权 state。

令牌只存服务端密文；API 只返回连接元信息，不回显 access_token / refresh_token。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import OAuthConnectionStatus


class OAuthConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """项目内一个外部平台账号的授权连接。

    `external_account_id` 是平台侧稳定身份；同一项目同一 provider 下唯一。
    令牌密文用 `secrets_box` 加密，撤销后清空。
    """

    __tablename__ = "oauth_connections"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "provider_code",
            "external_account_id",
            name="uq_oauth_connections_project_provider_external",
        ),
        Index("ix_oauth_connections_project_provider", "project_id", "provider_code"),
        Index("ix_oauth_connections_channel", "channel_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL")
    )
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_account_name: Mapped[str | None] = mapped_column(String(255))
    external_account_email: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    status: Mapped[OAuthConnectionStatus] = mapped_column(
        str_enum(OAuthConnectionStatus, "oauth_connection_status"),
        nullable=False,
        default=OAuthConnectionStatus.CONNECTED,
        server_default=OAuthConnectionStatus.CONNECTED.value,
    )
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_type: Mapped[str] = mapped_column(String(32), nullable=False, default="Bearer", server_default="Bearer")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")


class OAuthAuthorizationState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一次性授权 state：只存 SHA-256 摘要，回调时消费并标记。"""

    __tablename__ = "oauth_authorization_states"
    __table_args__ = (
        UniqueConstraint("state_hash", name="uq_oauth_authorization_states_state_hash"),
        Index("ix_oauth_authorization_states_expiry", "expires_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL")
    )
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    return_path: Mapped[str] = mapped_column(String(512), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""AI 引擎目录：系统级参考数据（不随项目变化），采样记录才带 project_id。

同一厂商的不同入口单独建 entry：用户端、API、应用内搜索分别采样，不能混为一谈。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import EngineEntryType, EngineProtocol


class AiEngine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_engines"
    __table_args__ = (UniqueConstraint("code", name="uq_ai_engines_code"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    vendor: Mapped[str] = mapped_column(String(64), nullable=False)
    supports_search: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supports_citation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    access_note: Mapped[str | None] = mapped_column(Text)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class AiEngineEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_engine_entries"
    __table_args__ = (
        UniqueConstraint("engine_id", "entry_type", "name", name="uq_ai_engine_entries_engine_type_name"),
        Index("ix_ai_engine_entries_active", "engine_id", "is_active"),
    )

    engine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_engines.id", ondelete="CASCADE"), nullable=False
    )
    entry_type: Mapped[EngineEntryType] = mapped_column(
        str_enum(EngineEntryType, "engine_entry_type"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_url: Mapped[str | None] = mapped_column(Text)
    protocol: Mapped[EngineProtocol] = mapped_column(
        str_enum(EngineProtocol, "engine_protocol"),
        nullable=False,
        default=EngineProtocol.CUSTOM,
        server_default=EngineProtocol.CUSTOM.value,
    )
    model_name: Mapped[str | None] = mapped_column(String(128))
    # 只存环境变量名，不存 API Key 明文；适配器运行时 os.getenv(credential_ref)。
    credential_ref: Mapped[str | None] = mapped_column(String(64))
    supports_search: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    access_note: Mapped[str | None] = mapped_column(Text)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

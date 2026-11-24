"""品牌实体配置模型：把「品牌叫什么」从项目名里解耦出来。

背景（为什么必须单独建表）：
- 原来品牌识别只认 `project.name` / `project.code`，而这两个值通常是内部代号
  （例如 `base-a` / `gz-base`），客户对外使用的品牌全称根本不在匹配表里，
  导致答案描述了品牌实体却稳定判 miss；
- 品牌名与项目名是两件事：项目名可能随运营改名，品牌名是对外口径，两者变动频率与责任人不同；
- 同一品牌在答案里可能以全名、简称、旧名、英文名出现，需要别名列表才能覆盖。

三类词条的分工见 `app/services/brand_profile.py` 的模块说明。
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class BrandProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """项目级品牌实体：一个项目一份，未配置时回退到项目名（保持历史可比）。"""

    __tablename__ = "brand_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_brand_profiles_project"),
        Index("ix_brand_profiles_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    # 对外正式名称：唯一必填字段，其余都可留空
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 别名：全名、简称、旧名、英文名；命中任一即 brand_mentioned=True
    aliases: Mapped[list[str] | None] = mapped_column(JSONB)
    # 唯一标识：地址、电话、公众号名等；命中任一即 brand_identified=True，不影响提及率
    identifiers: Mapped[list[str] | None] = mapped_column(JSONB)
    # 品牌自有域名：引用命中即 is_brand_related=True，用于信源占比
    owned_domains: Mapped[list[str] | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

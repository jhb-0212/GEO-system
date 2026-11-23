"""K8 微站：一个项目一个站，站内固定 6 个内容模块。

取舍清单 K8 的边界：
- 吸收：首页 / 产品服务 / 资讯 / PDF 资料 / 海报 / 名片 六类内容模块，可开关与排序；
- 拒绝：VR 全景、开屏广告、宣传视频、数字员工、智能体聊天（见 C3/C4），不做模板皮肤市场。

模块正文用 JSONB 存结构化内容（标题/段落/链接/图片 URL），渲染层只做「拼装」不解释语义，
这样后台改内容不需要发版，也不会把 markdown 解释器带进来。
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import SiteModuleType


class SiteSite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """项目微站身份：访问路径 /s/{slug}，未发布时公开接口一律 404。"""

    __tablename__ = "site_sites"
    __table_args__ = (UniqueConstraint("project_id", name="uq_site_sites_project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    intro: Mapped[str | None] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class SiteModule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """微站模块：每个站每种类型只有一条，避免「两个首页」这种歧义。"""

    __tablename__ = "site_modules"
    __table_args__ = (
        UniqueConstraint("site_id", "module_type", name="uq_site_modules_site_type"),
        Index("ix_site_modules_project_order", "project_id", "sort_order"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("site_sites.id", ondelete="CASCADE"), nullable=False
    )
    module_type: Mapped[SiteModuleType] = mapped_column(
        str_enum(SiteModuleType, "site_module_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

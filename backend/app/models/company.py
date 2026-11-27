"""企业档案：知识库的「公司层」实体，对标同类 GEO 平台的「基础信息 / 企业智能体画像」。

与 `facts` 的分工（这是本表唯一的口径边界，不要混用）：

- `facts` 是**可核验的权威事实**：逐条带来源、审批、版本、有效期，用于判断
  AI 回答「说得对不对」；
- `company_profiles` 是**对外表述与展示档案**：一段一段的文案（介绍 / 特点 /
  痛点 / 故事），用于生成、分发与建站，**不参与事实核验**。

所以：地址、电话、资质编号、成立日期这类可核验值，必须以 `facts` 为准。
本表保留 `business_phone / service_hotline / founded_on` 等字段只是为了对外展示，
保存时由接口做交叉校验，与 `facts` 冲突且未显式确认就拒绝写入——避免出现
「监测判说错，生产端还在复制错误」的第二份事实。
"""

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

# 对外画像的四种固定口径：同一家主体，对客户 / 候选人 / 参会方 / 活动受众说法不同。
# 「基础画像」就是 company_profiles 本身，不在这里再存一份，避免两处各说一套。
PROFILE_VIEW_KINDS: tuple[str, ...] = ("company", "recruit", "meeting", "activity")


class CompanyProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """项目级企业档案：一个项目一份。

    字数是平台侧的真实约束（公司介绍/创始人介绍 ≥100 且 ≤1000），在 schema 层校验，
    不放数据库 CHECK——文案规则会变，改约束成本比改代码高。
    """

    __tablename__ = "company_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_company_profiles_project"),
        Index("ix_company_profiles_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )

    # --- 标识 ---
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_name: Mapped[str | None] = mapped_column(String(255))
    slogan: Mapped[str | None] = mapped_column(String(255))
    province: Mapped[str | None] = mapped_column(String(64))
    headcount: Mapped[int | None] = mapped_column(Integer)
    founded_on: Mapped[date | None] = mapped_column(Date)

    # --- 联系方式（展示用；真值以 facts(contact) 为准）---
    business_phone: Mapped[str | None] = mapped_column(String(64))
    service_hotline: Mapped[str | None] = mapped_column(String(64))
    contact_email: Mapped[str | None] = mapped_column(String(255))

    # --- 列表类（一行一个 / 多选）---
    # 线下网点、官网地址：平台是「一行一个」的文本域，这里存字符串数组。
    stores: Mapped[list[str] | None] = mapped_column(JSONB)
    official_urls: Mapped[list[str] | None] = mapped_column(JSONB)
    industries: Mapped[list[str] | None] = mapped_column(JSONB)
    regions: Mapped[list[str] | None] = mapped_column(JSONB)
    # 产品信息：结构化条目，便于按产品生成问答与页面模块。
    products: Mapped[list[dict] | None] = mapped_column(JSONB)

    # --- 文案段 ---
    description: Mapped[str | None] = mapped_column(Text)
    highlights: Mapped[str | None] = mapped_column(Text)
    pain_points: Mapped[str | None] = mapped_column(Text)
    story: Mapped[str | None] = mapped_column(Text)
    founder_intro: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class CompanyProfileView(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """对外画像：企业 / 招聘 / 会议 / 活动 四套说法，一项目一 kind 一行。

    为什么单独建表而不是往 company_profiles 里塞 JSONB：
    四种画像的字段结构相同、但生命周期不同（招聘画像随岗位变、活动画像随活动下线），
    单独成行才能各自启停、各自记 updated_at，出问题时也查得到是哪一套口径被改过。
    `description / cautions` 是「对外怎么说」和「不要怎么说」，不参与事实核验——
    可核验值仍然以 facts 为准，这里只做表达。
    """

    __tablename__ = "company_profile_views"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", name="uq_company_profile_views_project_kind"),
        Index("ix_company_profile_views_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str | None] = mapped_column(String(128))
    audience: Mapped[str | None] = mapped_column(String(255))
    # 场景词：投喂生成与选题时用来锚定「在什么场景下说这句话」。
    scenario_words: Mapped[list[str] | None] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    cautions: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

class CompanyDraftModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """项目级起草模型配置：一键填表用哪个模型、哪把 Key。

    为什么按项目存而不是全局：
    - Key 的写入权限跟企业档案一致（brand.manage），全局配置会让任一项目的编辑
      改到所有项目的 Key；
    - 读取优先级是「项目配置 > 环境变量 > 引擎入口」，项目没配就回落到旧路径，
      不强求每个项目都配。

    `encrypted_secret` 与引擎入口同一套加密（`app.core.secrets_box`），接口只回显
    是否已配置，不回显值。
    """

    __tablename__ = "company_draft_models"
    __table_args__ = (UniqueConstraint("project_id", name="uq_company_draft_models_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    base_url: Mapped[str] = mapped_column(String(255), nullable=False, default="https://api.deepseek.com")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="deepseek-chat")
    encrypted_secret: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

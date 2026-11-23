"""项目对外渠道台账：一个渠道一条对外联系方式。

与企业档案的分工：企业档案里是「官方口径」（业务电话、售后热线、邮箱各一个），
这里是「对外露面矩阵」——公众号、小红书、抖音、门店电话等可能有多条，
每条自己标注对外公开还是仅内部使用。
"""

import uuid
from typing import Literal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

# 渠道枚举用代码常量而不是数据库原生枚举：新增渠道只需改这里，不必再跑迁移。
ContactChannel = Literal[
    "phone", "hotline", "email", "wechat", "wechat_official",
    "xiaohongshu", "douyin", "video_account", "website", "address", "other",
]

CHANNEL_LABELS: dict[str, str] = {
    "phone": "联系电话",
    "hotline": "售后热线",
    "email": "邮箱",
    "wechat": "微信",
    "wechat_official": "微信公众号",
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "video_account": "视频号",
    "website": "官网",
    "address": "地址",
    "other": "其他",
}


class ProjectContact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_contacts"
    __table_args__ = (
        UniqueConstraint("project_id", "channel", "value", name="uq_project_contacts_project_channel_value"),
        Index("ix_project_contacts_project_channel", "project_id", "channel"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    # 渠道下的具体值：电话号、邮箱、账号名、URL、门店地址等
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    # 备注名：例如「番禺校区前台」「招生咨询」；同一渠道多条时用于区分
    label: Mapped[str | None] = mapped_column(String(64))
    # 是否对外公开：false 表示仅内部对接用，不进入对外材料
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

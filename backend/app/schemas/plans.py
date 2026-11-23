"""运营计划请求模型：计划/排期与内容、渠道、公开站页面关联。"""

from datetime import datetime
import uuid

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ContentPlanStatus, PlanType


class PlanCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    plan_type: PlanType
    channel_id: uuid.UUID | None = None
    content_item_id: uuid.UUID | None = None
    site_page_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    status: ContentPlanStatus = ContentPlanStatus.PROPOSED
    notes: str | None = Field(default=None, max_length=5000)
    # B7 新媒体发布记录：是否已发布 / 发布链接 / 播放互动人工备注
    is_published: bool = False
    publish_url: str | None = Field(default=None, max_length=500)
    play_note: str | None = Field(default=None, max_length=5000)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean


class PlanUpdate(BaseModel):
    """局部更新；显式 null 清空可空关联，不传保持原值。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    plan_type: PlanType | None = None
    channel_id: uuid.UUID | None = None
    content_item_id: uuid.UUID | None = None
    site_page_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    status: ContentPlanStatus | None = None
    notes: str | None = Field(default=None, max_length=5000)
    is_published: bool | None = None
    publish_url: str | None = Field(default=None, max_length=500)
    play_note: str | None = Field(default=None, max_length=5000)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean

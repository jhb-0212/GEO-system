"""公开站事实页登记模型：slug 是稳定 URL，创建后不再改。"""

import uuid

from pydantic import BaseModel, Field, field_validator

from app.models.enums import PagePublishStatus, PageType


class PageCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    page_type: PageType
    url: str = Field(min_length=1, max_length=2000)
    canonical_url: str | None = Field(default=None, max_length=2000)
    publish_status: PagePublishStatus = PagePublishStatus.DRAFT
    content_item_id: uuid.UUID | None = None

    @field_validator("slug", "title", "url", "canonical_url")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean


class PageUpdate(BaseModel):
    """局部更新；slug 不可改，避免已登记 URL 漂移。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    page_type: PageType | None = None
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    canonical_url: str | None = Field(default=None, max_length=2000)
    publish_status: PagePublishStatus | None = None
    content_item_id: uuid.UUID | None = None

    @field_validator("title", "url", "canonical_url")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean

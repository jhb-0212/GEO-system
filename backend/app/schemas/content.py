"""内容与审核请求模型。"""

import uuid

from pydantic import BaseModel, Field

from app.models.enums import ContentKind, ReviewDecision


class ContentItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    kind: ContentKind = ContentKind.MASTER
    channel_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None


class ContentVersionCreate(BaseModel):
    body: str = Field(min_length=1)
    change_note: str | None = None


class ContentBodyUpdate(BaseModel):
    body: str = Field(min_length=1)
    change_note: str | None = None


class ContentReviewRequest(BaseModel):
    decision: ReviewDecision
    comment: str | None = None

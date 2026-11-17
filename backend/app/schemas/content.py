"""内容与审核请求模型。"""

import uuid

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ContentKind, ReviewDecision


class ContentItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    kind: ContentKind = ContentKind.MASTER
    channel_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validate_kind_links(self) -> "ContentItemCreate":
        """渠道稿必须同时挂母稿与渠道；母稿不得反向挂渠道或父稿。

        这是模型注释里的业务约束，不能只写在文档里。Pydantic 校验负责 API
        入口，数据库仍有同名 CHECK 约束兜底直接 SQL 写入。
        """
        if self.kind is ContentKind.CHANNEL:
            if self.parent_id is None or self.channel_id is None:
                raise ValueError("渠道稿必须同时指定母稿 parent_id 与渠道 channel_id")
        elif self.parent_id is not None or self.channel_id is not None:
            raise ValueError("母稿不能指定 parent_id 或 channel_id")
        return self


class ContentVersionCreate(BaseModel):
    body: str = Field(min_length=1)
    change_note: str | None = None


class ContentBodyUpdate(BaseModel):
    body: str = Field(min_length=1)
    change_note: str | None = None


class ContentReviewRequest(BaseModel):
    decision: ReviewDecision
    comment: str | None = None

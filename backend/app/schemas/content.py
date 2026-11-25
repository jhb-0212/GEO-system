"""内容与审核请求模型。"""

import uuid

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ContentFormat, ContentKind, ContentStatus, ReviewDecision


class ContentItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    kind: ContentKind = ContentKind.MASTER
    content_type: ContentFormat | None = None
    channel_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validate_kind_links(self) -> "ContentItemCreate":
        """渠道稿必须同时挂母稿与渠道；母稿不得反向挂渠道或父稿。

        这是模型注释里的业务约束，不能只写在文档里。Pydantic 校验负责 API
        入口，数据库仍有同名 CHECK 约束兜底直接 SQL 写入。
        """
        if self.kind == ContentKind.CHANNEL:
            if self.parent_id is None or self.channel_id is None:
                raise ValueError("渠道稿必须同时指定母稿 parent_id 与渠道 channel_id")
            if self.content_type is not None:
                raise ValueError("渠道稿的内容形式继承母稿，创建时不要单独指定")
        elif self.parent_id is not None or self.channel_id is not None:
            raise ValueError("母稿不能指定 parent_id 或 channel_id")
        return self


class ContentVersionCreate(BaseModel):
    body: str = Field(min_length=1, max_length=200_000)
    change_note: str | None = Field(default=None, max_length=2_000)


class ContentBodyUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=200_000)
    change_note: str | None = Field(default=None, max_length=2_000)


class ContentReviewRequest(BaseModel):
    decision: ReviewDecision
    comment: str | None = None


class ContentStatusUpdate(BaseModel):
    """内容状态手动迁移：只开放排期与需关注，已发布由发布回执结案。"""

    status: ContentStatus


class ContentVersionLinksUpdate(BaseModel):
    """整版关联替换：题目、证据与权威事实都按版本级集合覆盖，传空数组即清空。"""

    question_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    citation_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    fact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    # 事实修订后，只有显式确认才把关联版本推进到当前值，避免保存动作静默“祝福”新事实
    confirm_fact_revisions: bool = False


class SellingPointCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    value_text: str | None = Field(default=None, max_length=2_000)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    required: bool = True
    note: str | None = Field(default=None, max_length=2_000)


class SellingPointUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    value_text: str | None = Field(default=None, max_length=2_000)
    aliases: list[str] | None = Field(default=None, max_length=20)
    required: bool | None = None
    is_active: bool | None = None
    note: str | None = Field(default=None, max_length=2_000)

"""引用复核请求模型（B6）：路由层只做编排，入参校验集中在这里。"""

import uuid

from pydantic import BaseModel, Field

from app.models.enums import CitationPageType, CitationReviewStatus, SourceCategory


class CitationSourceClassifyRequest(BaseModel):
    """人工给未知被引域名定来源类别；只做来源分类，不创建发布渠道。"""

    source_category: SourceCategory
    review_note: str | None = Field(default=None, max_length=500)


class CitationReviewRequest(BaseModel):
    """确认或驳回归属。

    - `review_status` 手动提交只允许 `manual_confirmed` / `manual_rejected`，`auto` 由系统
      回填，不能通过本接口回写。
    - `channel_id` / `competitor_id` 允许改挂，但两个 ID 都必须属于当前项目且存在，否则
      404 `resource_missing`；显式 `null` 清空映射；不传则保持原值。本接口不允许改 `raw_url`。
    """

    review_status: CitationReviewStatus
    review_note: str | None = Field(default=None, max_length=500)
    channel_id: uuid.UUID | None = None
    competitor_id: uuid.UUID | None = None
    is_brand_related: bool | None = Field(
        default=None,
        description="人工纠正引用是否品牌相关；显式传值才覆盖，留空保持自动判定。",
    )


class CitationPageTypeRequest(BaseModel):
    """人工覆盖单条引用的页面类型；页面类型按引用记录，不按域名批量改。"""

    page_type: CitationPageType

"""线索请求模型。"""

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.enums import EnrollmentStatus


class LeadCreate(BaseModel):
    contact_name: str | None = Field(default=None, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=64)
    contact_wechat: str | None = Field(default=None, max_length=64)
    interested_course: str | None = Field(default=None, max_length=128)
    reported_ai_product: str | None = Field(
        default=None,
        max_length=64,
        description="咨询时用户自报使用的 AI 产品；自由文本，不做固定枚举",
    )
    is_valid: bool = Field(default=True, description="线索/客服判定是否为有效线索")
    lead_source: str | None = Field(default=None, max_length=64)
    source_question_id: UUID | None = None
    source_channel_id: UUID | None = None
    source_engine_id: UUID | None = None
    source_sample_id: UUID | None = Field(default=None, description="监测样本令牌解析后的内部 ID，不公开展示")
    source_content_item_id: UUID | None = None
    article_url: str | None = Field(default=None, max_length=512)
    landing_url: str | None = Field(default=None, max_length=512)
    session_id: str | None = Field(default=None, max_length=64)
    utm_campaign: str | None = Field(default=None, max_length=128)
    note: str | None = None
    # B4：只收原文地址，服务端立刻哈希入 ip_hash；不提供「直接写哈希」的入口
    visitor_ip: str | None = Field(default=None, max_length=64)
    visitor_region: str | None = Field(default=None, max_length=64)


class LeadUpdate(BaseModel):
    """跟进写操作：可改状态、有效性、自报产品、备注和负责人，不改归因字段。"""

    enrollment_status: EnrollmentStatus | None = None
    is_valid: bool | None = None
    reported_ai_product: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=5000)
    owner_id: UUID | None = None

    @model_validator(mode="after")
    def validate_non_nullable_updates(self):
        """显式 null 不是合法的非空字段值；不能让非空列写入 None。"""
        for field in ("enrollment_status", "is_valid"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} 不能为 null")
        return self


class LeadMessageCreate(BaseModel):
    """留言：访客提交只需 body；运营侧回复可带最小 1 字。"""

    body: str = Field(min_length=1, max_length=2000)
    author_role: str = Field(default="visitor", pattern=r"^(visitor|staff)$")

    @model_validator(mode="after")
    def strip_body(self):
        clean = self.body.strip()
        if not clean:
            raise ValueError("留言不能为空")
        self.body = clean
        return self


class LeadAutoreplyIn(BaseModel):
    """留言固定话术配置：开关 + 一句预先写好、品牌已确认的模板句。"""

    enabled: bool
    script: str = Field(default="", max_length=500)
    include_contact: bool = True
    note: str | None = Field(default=None, max_length=200)

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
    is_valid: bool = Field(default=True, description="招生/客服判定是否为有效线索")
    lead_source: str | None = Field(default=None, max_length=64)
    source_question_id: UUID | None = None
    source_channel_id: UUID | None = None
    source_engine_id: UUID | None = None
    landing_url: str | None = Field(default=None, max_length=512)
    session_id: str | None = Field(default=None, max_length=64)
    utm_campaign: str | None = Field(default=None, max_length=128)
    note: str | None = None


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

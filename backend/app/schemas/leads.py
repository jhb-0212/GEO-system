"""线索请求模型。"""

from uuid import UUID

from pydantic import BaseModel, Field


class LeadCreate(BaseModel):
    contact_name: str | None = Field(default=None, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=64)
    contact_wechat: str | None = Field(default=None, max_length=64)
    interested_course: str | None = Field(default=None, max_length=128)
    lead_source: str | None = Field(default=None, max_length=64)
    source_question_id: UUID | None = None
    source_channel_id: UUID | None = None
    source_engine_id: UUID | None = None
    landing_url: str | None = Field(default=None, max_length=512)
    utm_campaign: str | None = Field(default=None, max_length=128)
    note: str | None = None

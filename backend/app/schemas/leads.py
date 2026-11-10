"""线索请求模型。"""

from pydantic import BaseModel, Field


class LeadCreate(BaseModel):
    contact_name: str | None = Field(default=None, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=64)
    contact_wechat: str | None = Field(default=None, max_length=64)
    interested_course: str | None = Field(default=None, max_length=128)
    lead_source: str | None = Field(default=None, max_length=64)
    note: str | None = None

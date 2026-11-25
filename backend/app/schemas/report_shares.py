"""月报分享请求模型：创建、公开密码访问。"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator


class ReportShareCreate(BaseModel):
    snapshot_id: uuid.UUID
    label: str | None = Field(None, max_length=120, description="内部备注，不对客户显示")
    password: str | None = Field(None, min_length=6, max_length=72, description="可选访问密码，至少 6 位")
    expires_in_days: int = Field(30, ge=1, le=365, description="有效天数，1–365")
    brand_name: str | None = Field(None, max_length=80, description="白标显示名，留空用项目名")
    brand_logo_url: str | None = Field(None, max_length=500, description="白标 Logo 的 http(s) 地址")
    accent_color: str = Field("#2563eb", pattern=r"^#[0-9a-fA-F]{6}$", description="客户报告主色")
    contact_text: str | None = Field(None, max_length=200, description="页脚联系说明")
    show_leads: bool = Field(False, description="是否向客户展示报告中的线索段")

    @field_validator("password")
    @classmethod
    def _password_bytes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if len(clean.encode("utf-8")) > 72:
            raise ValueError("密码不能超过 72 字节（中文约 24 个汉字）")
        return clean


class ReportSharePassword(BaseModel):
    password: str | None = Field(None, max_length=72)

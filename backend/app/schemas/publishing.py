"""发布请求模型。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import AttemptResult, PublishMode, VerifyOutcome


def _validate_publish_url(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    if not clean.startswith(("http://", "https://")):
        raise ValueError("published_url 必须以 http:// 或 https:// 开头")
    return clean


class PublishAttemptCreate(BaseModel):
    result: AttemptResult = AttemptResult.SUCCESS
    mode: PublishMode = PublishMode.MANUAL
    error_code: str | None = None
    error_note: str | None = None


class PublishTaskCreate(BaseModel):
    version_id: uuid.UUID
    channel_id: uuid.UUID
    account_id: uuid.UUID
    publish_mode: PublishMode = PublishMode.MANUAL
    # 业务批次键，调用方必填；与账号/渠道/版本组成四元组幂等，仅做分组，服务端不填默认。
    task_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    scheduled_at: datetime | None = None


class PublishReceiptCreate(BaseModel):
    published_url: str = Field(min_length=1, max_length=2048)
    receipt_payload: dict[str, Any] | None = None
    attempt_id: uuid.UUID | None = None

    @field_validator("published_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return _validate_publish_url(value)


class PublishVerifyRequest(BaseModel):
    outcome: VerifyOutcome
    # 核实已发出必须带真实 URL 写回执结案；未发出时忽略。缺失则 422，不写 receipt、不结案。
    published_url: str | None = Field(default=None, min_length=1, max_length=2048)
    receipt_payload: dict[str, Any] | None = None

    @field_validator("published_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        return _validate_publish_url(value)

    @model_validator(mode="after")
    def _require_url_when_published(self) -> "PublishVerifyRequest":
        if self.outcome == VerifyOutcome.PUBLISHED and not self.published_url:
            raise ValueError("核实已发出时必须提供 published_url")
        return self

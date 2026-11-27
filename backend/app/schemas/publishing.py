"""发布请求模型。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.credentials import is_allowed_credential_ref
from app.models.enums import AttemptResult, PublishHandoffReason, PublishMode, VerifyOutcome
from app.services.url_policy import validate_public_http_url


def _validate_publish_url(value: str | None) -> str | None:
    return validate_public_http_url(value, field_name="published_url")


class PublishAccountCreate(BaseModel):
    channel_id: uuid.UUID
    account_name: str = Field(min_length=1, max_length=128)
    credential_ref: str | None = Field(default=None, max_length=255)
    # 只接收连接 ID，不接收 access/refresh token；服务端再校验连接状态与渠道归属。
    oauth_connection_id: uuid.UUID | None = None
    notes: str | None = None

    @field_validator("account_name")
    @classmethod
    def _clean_account_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("account_name 不能为空")
        return clean

    @field_validator("credential_ref")
    @classmethod
    def _clean_credential_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if not is_allowed_credential_ref(clean):
            raise ValueError("credential_ref 只接受受控密钥变量名（以 _API_KEY/_TOKEN 等结尾）")
        return clean


class PublishAccountUpdate(BaseModel):
    """发布账号换绑：渠道不变，只改账号名、凭证引用、备注和启停。"""

    account_name: str | None = Field(default=None, max_length=128)
    credential_ref: str | None = Field(default=None, max_length=255)
    oauth_connection_id: uuid.UUID | None = None
    notes: str | None = None
    is_active: bool | None = None

    @field_validator("account_name")
    @classmethod
    def _clean_account_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("account_name 不能为空")
        return clean

    @field_validator("credential_ref")
    @classmethod
    def _clean_credential_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if not is_allowed_credential_ref(clean):
            raise ValueError("credential_ref 只接受受控密钥变量名（以 _API_KEY/_TOKEN 等结尾）")
        return clean


class PublishAttemptCreate(BaseModel):
    result: AttemptResult = AttemptResult.SUCCESS
    mode: PublishMode = PublishMode.MANUAL
    error_code: str | None = None
    error_note: str | None = None


class PublishHandoffCreate(BaseModel):
    """自动发布被扫码/验证码/登录态阻断时，显式转人工，不发外部请求。"""

    reason: PublishHandoffReason
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _require_note_for_other(self):
        if self.reason == PublishHandoffReason.OTHER and not (self.note or "").strip():
            raise ValueError("reason=other 时必须填写 note")
        return self


class PublishTaskCreate(BaseModel):
    version_id: uuid.UUID
    channel_id: uuid.UUID
    account_id: uuid.UUID
    publish_mode: PublishMode = PublishMode.MANUAL
    # 业务批次键，调用方必填；与账号/渠道/版本组成四元组幂等，仅做分组，服务端不填默认。
    task_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    scheduled_at: datetime | None = None


class PublishWeChatExecuteRequest(BaseModel):
    """执行一条微信公众号任务；`/execute` 走 freepublish（永久链接），`/mass-send` 才群发。

    不接受任意平台地址，`content_source_url` 也要过 URL 校验。
    """

    author: str | None = Field(default=None, max_length=64)
    digest: str | None = Field(default=None, max_length=120)
    thumb_media_id: str | None = Field(default=None, max_length=128)
    content_source_url: str | None = Field(default=None, max_length=2048)

    @field_validator("content_source_url")
    @classmethod
    def _check_source_url(cls, value: str | None) -> str | None:
        return _validate_publish_url(value)


class PublishReceiptCreate(BaseModel):
    published_url: str = Field(min_length=1, max_length=2048)
    receipt_payload: dict[str, Any] | None = None
    attempt_id: uuid.UUID | None = None
    # P76：回执落库时可直接挂到已批准的媒体投放预算；也可之后在预算详情里挂。
    budget_approval_id: uuid.UUID | None = None

    @field_validator("published_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return _validate_publish_url(value)


class PublishVerifyRequest(BaseModel):
    outcome: VerifyOutcome
    # 核实已发出必须带真实 URL 写回执结案；未发出时忽略。缺失则 422，不写 receipt、不结案。
    published_url: str | None = Field(default=None, min_length=1, max_length=2048)
    receipt_payload: dict[str, Any] | None = None
    budget_approval_id: uuid.UUID | None = None

    @field_validator("published_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        return _validate_publish_url(value)

    @model_validator(mode="after")
    def _require_url_when_published(self) -> "PublishVerifyRequest":
        if self.outcome == VerifyOutcome.PUBLISHED and not self.published_url:
            raise ValueError("核实已发出时必须提供 published_url")
        return self

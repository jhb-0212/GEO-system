"""页面级发布审批请求模型。"""

import uuid

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import CitationPageType, PagePermission, ReviewDecision
from app.services.url_policy import validate_public_http_url


class PageApprovalCreate(BaseModel):
    channel_id: uuid.UUID
    page_url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=255)
    page_type: CitationPageType
    permission: PagePermission

    @field_validator("page_url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        return validate_public_http_url(value, field_name="page_url")

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        return clean or None


class PageApprovalReview(BaseModel):
    decision: ReviewDecision
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _require_reject_note(self):
        if self.decision == ReviewDecision.REJECTED and not (self.note or "").strip():
            raise ValueError("驳回页面审批必须填写意见")
        return self


class PageApprovalRevoke(BaseModel):
    note: str = Field(min_length=1, max_length=1000)

    @field_validator("note")
    @classmethod
    def _clean_note(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("撤销页面审批必须填写原因")
        return clean

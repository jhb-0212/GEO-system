"""权威事实库与回答事实核验请求模型。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    CorrectionTaskStatus,
    FactClaimVerdict,
    FactType,
    ReviewDecision,
)


class FactCreate(BaseModel):
    fact_type: FactType
    fact_key: str = Field(min_length=1, max_length=128)
    fact_value: str = Field(min_length=1, max_length=5000)
    source_document: str | None = Field(default=None, max_length=5000)
    source_url: str | None = Field(default=None, max_length=1024)
    owner: str | None = Field(default=None, max_length=128)
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    business_confirmed: bool = False
    business_confirmed_note: str | None = Field(default=None, max_length=2000)
    change_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _validate_effective_window(self) -> "FactCreate":
        if self.effective_from and self.effective_until and self.effective_until < self.effective_from:
            raise ValueError("生效结束时间不能早于开始时间")
        return self


class FactUpdate(BaseModel):
    fact_key: str | None = Field(default=None, min_length=1, max_length=128)
    fact_value: str | None = Field(default=None, min_length=1, max_length=5000)
    source_document: str | None = Field(default=None, max_length=5000)
    source_url: str | None = Field(default=None, max_length=1024)
    owner: str | None = Field(default=None, max_length=128)
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    business_confirmed: bool | None = None
    business_confirmed_note: str | None = Field(default=None, max_length=2000)
    change_note: str | None = Field(default=None, max_length=2000)


class FactReviewRequest(BaseModel):
    decision: ReviewDecision
    comment: str | None = Field(default=None, max_length=2000)
    business_confirmed: bool = False
    business_confirmed_note: str | None = Field(default=None, max_length=2000)


class FactClaimCreate(BaseModel):
    claim_text: str = Field(min_length=1, max_length=5000)
    fact_id: uuid.UUID | None = None
    citation_id: uuid.UUID | None = None
    source_url: str | None = Field(default=None, max_length=1024)


class FactClaimReviewRequest(BaseModel):
    verdict: FactClaimVerdict
    review_note: str | None = Field(default=None, max_length=2000)
    create_correction_task: bool = True


class CorrectionTaskUpdate(BaseModel):
    status: CorrectionTaskStatus
    note: str | None = Field(default=None, max_length=2000)

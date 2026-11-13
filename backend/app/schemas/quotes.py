"""媒体报价请求模型：提交走 content.write，审批走 content.review。"""

from decimal import Decimal
import uuid

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ReviewDecision


class QuoteCreate(BaseModel):
    plan_id: uuid.UUID
    channel_id: uuid.UUID | None = None
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    quantity: int = Field(default=1, ge=1, le=10000)
    currency: str = Field(default="CNY", min_length=1, max_length=8)
    note: str | None = Field(default=None, max_length=5000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        clean = value.strip().upper()
        if not clean:
            raise ValueError("不能为空")
        return clean


class QuoteUpdate(BaseModel):
    """待审批报价可改；已审批/驳回后锁定，不重新打开。"""

    channel_id: uuid.UUID | None = None
    unit_price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    quantity: int | None = Field(default=None, ge=1, le=10000)
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    note: str | None = Field(default=None, max_length=5000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip().upper()
        if not clean:
            raise ValueError("不能为空")
        return clean


class QuoteReview(BaseModel):
    decision: ReviewDecision
    note: str | None = Field(default=None, max_length=5000)

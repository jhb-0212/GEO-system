"""预算审批请求模型：四类费用统一申请，审批只允许 pending → approved/rejected。"""

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import BudgetCategory, ReviewDecision


class BudgetApprovalCreate(BaseModel):
    category: BudgetCategory
    # P76：仅 media_placement 使用；是否必填由业务层结合报价状态校验。
    media_quote_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    unit: str | None = Field(default=None, max_length=32)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="CNY", min_length=3, max_length=8)
    note: str | None = Field(default=None, max_length=5000)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title 不能为空")
        return value

    @field_validator("currency")
    @classmethod
    def currency_normalized(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("currency 不能为空")
        return value

    @model_validator(mode="after")
    def validate_amount(self):
        """给了数量与单价时必须能对上金额，避免审批表和明细口径分叉。"""
        if self.quantity is not None and self.unit_price is not None:
            expected = (self.quantity * self.unit_price).quantize(Decimal("0.01"))
            if expected != self.amount:
                raise ValueError("amount 必须等于 quantity × unit_price")
        return self


class BudgetApprovalReview(BaseModel):
    decision: ReviewDecision
    note: str | None = Field(default=None, max_length=5000)


class BudgetReceiptLinkCreate(BaseModel):
    receipt_id: uuid.UUID

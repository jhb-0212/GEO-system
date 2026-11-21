"""P76 预算-报价-回执关联校验。

约束集中在服务层，预算创建/审批与回执创建/挂接共用同一套规则：
- 媒体投放预算必须指向已批准的 media_quote；
- 数量、单价、币种、金额必须与报价一致，且同报价预算总量不超过报价篇数；
- 回执只能挂到已批准、同项目、同渠道的媒体预算，一条回执最多挂一个预算。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    BusinessValidationError,
    ConflictError,
    ResourceMissingError,
)
from app.models import BudgetApproval, MediaQuote, PublishReceipt, PublishTask
from app.models.enums import (
    BudgetApprovalStatus,
    BudgetCategory,
    QuoteStatus,
)

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _enum_value(value) -> str:
    return getattr(value, "value", str(value))


def quote_used_quantity(
    db: Session,
    *,
    media_quote_id: uuid.UUID,
    exclude_budget_id: uuid.UUID | None = None,
) -> Decimal:
    """同一报价已被 pending/approved 预算占用的篇数；驳回不占额度。"""
    filters = [
        BudgetApproval.media_quote_id == media_quote_id,
        BudgetApproval.status.in_(
            [BudgetApprovalStatus.PENDING, BudgetApprovalStatus.APPROVED]
        ),
    ]
    if exclude_budget_id is not None:
        filters.append(BudgetApproval.id != exclude_budget_id)
    total = db.scalar(
        select(func.coalesce(func.sum(BudgetApproval.quantity), 0)).where(*filters)
    )
    return Decimal(str(total or 0))


def validate_media_budget_quote(
    db: Session,
    *,
    project_id: uuid.UUID,
    category: BudgetCategory,
    media_quote_id: uuid.UUID | None,
    quantity: Decimal | None,
    unit_price: Decimal | None,
    amount: Decimal,
    currency: str,
    exclude_budget_id: uuid.UUID | None = None,
) -> MediaQuote | None:
    """校验预算与报价的一致性；非媒体预算返回 None。"""
    if category != BudgetCategory.MEDIA_PLACEMENT:
        if media_quote_id is not None:
            raise BusinessValidationError(
                "只有媒体投放预算可以关联媒体报价", code="media_quote_not_allowed"
            )
        return None

    if media_quote_id is None:
        raise BusinessValidationError(
            "媒体投放预算必须关联已批准的媒体报价", code="media_quote_required"
        )
    if quantity is None or quantity <= ZERO:
        raise BusinessValidationError(
            "媒体投放预算必须填写大于 0 的篇数", code="budget_quote_quantity_required"
        )

    quote = db.scalar(
        select(MediaQuote)
        .where(
            MediaQuote.project_id == project_id,
            MediaQuote.id == media_quote_id,
        )
        .with_for_update()
    )
    if quote is None:
        raise ResourceMissingError("媒体报价不存在", code="media_quote_missing")
    if quote.status != QuoteStatus.APPROVED:
        raise BusinessValidationError(
            "媒体报价未审批通过，不能作为预算单价依据",
            code="media_quote_not_approved",
        )

    try:
        budget_quantity = Decimal(quantity)
        budget_unit_price = Decimal(unit_price) if unit_price is not None else None
        budget_amount = Decimal(amount)
    except (InvalidOperation, TypeError) as exc:
        raise BusinessValidationError(
            "预算数量、单价或金额格式不正确", code="budget_amount_invalid"
        ) from exc

    if budget_quantity != budget_quantity.to_integral_value():
        raise BusinessValidationError(
            "媒体投放预算数量必须是整数篇数", code="budget_quote_quantity_not_integer"
        )
    if budget_unit_price is None or budget_unit_price.quantize(CENT) != quote.unit_price.quantize(CENT):
        raise BusinessValidationError(
            "预算单价必须等于已批准报价单价", code="budget_quote_unit_price_mismatch"
        )
    if currency.strip().upper() != quote.currency.strip().upper():
        raise BusinessValidationError(
            "预算币种必须等于报价币种", code="budget_quote_currency_mismatch"
        )
    expected_amount = (budget_quantity * quote.unit_price).quantize(CENT)
    if budget_amount.quantize(CENT) != expected_amount:
        raise BusinessValidationError(
            "预算金额必须等于数量 × 报价单价", code="budget_amount_mismatch"
        )

    used = quote_used_quantity(
        db, media_quote_id=quote.id, exclude_budget_id=exclude_budget_id
    )
    remaining = Decimal(quote.quantity) - used
    if budget_quantity > remaining:
        raise BusinessValidationError(
            f"超过报价剩余篇数：报价 {quote.quantity} 篇，已占用 {used} 篇，剩余 {max(remaining, ZERO)} 篇",
            code="budget_quote_quantity_exceeded",
        )
    return quote


def receipt_link_summary(db: Session, budget: BudgetApproval) -> tuple[int, int]:
    """返回 (已挂回执数, 剩余可挂数)。"""
    count = (
        db.scalar(
            select(func.count())
            .select_from(PublishReceipt)
            .where(PublishReceipt.budget_approval_id == budget.id)
        )
        or 0
    )
    total = int(budget.quantity or 0)
    return int(count), max(total - int(count), 0)


def _receipt_host(published_url: str) -> str:
    return (urlparse(published_url).hostname or "").lower()


def _is_example_url(published_url: str) -> bool:
    host = _receipt_host(published_url)
    return host == "example.com" or host.endswith(".example.com")


def link_receipt_to_budget(
    db: Session,
    *,
    project_id: uuid.UUID,
    budget: BudgetApproval,
    receipt: PublishReceipt,
) -> tuple[int, int]:
    """把一条回执挂到预算；返回 (已挂回执数, 剩余可挂数)。"""
    if _enum_value(budget.status) != BudgetApprovalStatus.APPROVED.value:
        raise ConflictError("预算未审批通过，不能挂回执", code="budget_not_approved")
    if _enum_value(budget.category) != BudgetCategory.MEDIA_PLACEMENT.value:
        raise BusinessValidationError(
            "只有媒体投放预算可以挂发布回执",
            code="budget_receipt_link_requires_media",
        )
    if budget.media_quote_id is None:
        raise ConflictError("预算未关联媒体报价，不能挂回执", code="budget_quote_missing")

    quote = db.scalar(
        select(MediaQuote).where(
            MediaQuote.project_id == project_id,
            MediaQuote.id == budget.media_quote_id,
        )
    )
    if quote is None:
        raise ResourceMissingError("媒体报价不存在", code="media_quote_missing")
    if quote.channel_id is None:
        raise ConflictError(
            "媒体报价未指定渠道，无法校验回执渠道归属",
            code="budget_quote_channel_missing",
        )

    task = db.scalar(
        select(PublishTask).where(
            PublishTask.project_id == project_id,
            PublishTask.id == receipt.task_id,
        )
    )
    if task is None:
        raise ResourceMissingError("回执对应的发布任务不存在", code="publish_task_missing")
    if task.channel_id != quote.channel_id:
        raise BusinessValidationError(
            "回执任务渠道与报价渠道不一致", code="budget_receipt_channel_mismatch"
        )
    if _is_example_url(receipt.published_url):
        raise BusinessValidationError(
            "example.com 测试回执不能挂入试点预算",
            code="budget_receipt_test_url_not_allowed",
        )
    if receipt.budget_approval_id is not None:
        raise ConflictError(
            "该回执已挂到其他预算，请先解绑", code="budget_receipt_already_linked"
        )

    linked, remaining = receipt_link_summary(db, budget)
    if linked >= int(budget.quantity or 0):
        raise ConflictError(
            "该预算已挂满回执，不能继续挂接", code="budget_receipt_quantity_exceeded"
        )

    receipt.budget_approval_id = budget.id
    db.flush()
    return linked + 1, max(int(budget.quantity or 0) - linked - 1, 0)


def unlink_receipt_from_budget(
    db: Session,
    *,
    project_id: uuid.UUID,
    budget: BudgetApproval,
    receipt: PublishReceipt,
) -> tuple[int, int]:
    if receipt.budget_approval_id != budget.id:
        raise ConflictError(
            "该回执未挂到当前预算，不能解绑", code="budget_receipt_not_linked"
        )
    receipt.budget_approval_id = None
    db.flush()
    linked, remaining = receipt_link_summary(db, budget)
    return linked, remaining

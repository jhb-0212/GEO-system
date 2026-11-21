"""页面级发布审批规则：逐页匹配与回执闸门；域名归属暂不校验。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ReviewStateError
from app.models import Channel, PageApproval
from app.models.enums import (
    ChannelCategory,
    CitationPageType,
    PageApprovalStatus,
    PagePermission,
)
from app.services.citation_attribution import url_key
from app.services.citation_classification import classify_citation

# 院校类渠道和招生/招聘页是高风险发布面，必须逐页审批。
# 媒体、百科等第三方页面可以登记 third_party 作为引用来源，但不作为官方发布页。
PAGE_APPROVAL_REQUIRED_PAGE_TYPES = frozenset(
    {CitationPageType.ADMISSIONS, CitationPageType.RECRUITMENT}
)
PAGE_APPROVAL_REQUIRED_CATEGORIES = frozenset({ChannelCategory.INSTITUTION})
PUBLISHABLE_PERMISSIONS = frozenset({PagePermission.OFFICIAL, PagePermission.AUTHORIZED})


def page_type_for_url(url: str, title: str | None = None) -> CitationPageType:
    return classify_citation(domain=None, url=url, title=title).page_type


def find_page_approval(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel_id: uuid.UUID,
    page_url: str,
) -> PageApproval | None:
    return db.scalar(
        select(PageApproval).where(
            PageApproval.project_id == project_id,
            PageApproval.channel_id == channel_id,
            PageApproval.url_key == url_key(page_url),
        )
    )


def page_approval_required(channel: Channel, page_type: CitationPageType) -> bool:
    return (
        page_type in PAGE_APPROVAL_REQUIRED_PAGE_TYPES
        or channel.category in PAGE_APPROVAL_REQUIRED_CATEGORIES
    )


def require_publishable_page_approval(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel: Channel,
    published_url: str,
) -> PageApproval | None:
    """回执落库前校验：高风险页面必须有同 URL、同页型的已批准发布页审批。

    普通页面（非院校渠道、非招生/招聘页）返回 None，不改变现有发布流程；
    一旦命中，third_party 审批也不能作为官方发布依据。
    """
    page_type = page_type_for_url(published_url)
    approval = find_page_approval(
        db,
        project_id=project_id,
        channel_id=channel.id,
        page_url=published_url,
    )
    if approval is not None:
        page_type = page_type_for_url(published_url, approval.title)
    if not page_approval_required(channel, page_type):
        return None
    if approval is None:
        raise ReviewStateError(
            "该页面属于院校/招生/招聘高风险页，回执落库前必须先完成页面级审批",
            code="page_approval_required",
        )
    if approval.status != PageApprovalStatus.APPROVED:
        raise ReviewStateError(
            f"页面审批状态为 {approval.status.value}，不能作为发布回执依据",
            code="page_approval_not_approved",
        )
    if approval.page_type != page_type:
        raise ReviewStateError(
            "页面审批登记的页型与实际 URL 分类不一致，请先修正审批记录",
            code="page_approval_type_mismatch",
        )
    if approval.permission not in PUBLISHABLE_PERMISSIONS:
        raise ReviewStateError(
            "第三方页面审批只能作为引用来源，不能作为官方发布页",
            code="page_approval_not_publishable",
        )
    return approval


def page_approval_can_publish(approval: PageApproval) -> bool:
    return approval.status == PageApprovalStatus.APPROVED and approval.permission in PUBLISHABLE_PERMISSIONS

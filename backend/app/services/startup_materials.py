"""启动材料盘点：域名/CMS、平台账号、路线大纲、授权案例、招生就业口径。

只读真实库字段；测试账号、空凭据和敏感草稿一律进待补清单，不用“有记录”冒充“可发布”。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BrandProfile, ContentItem, Faq, Material, PublicPage, PublishAccount
from app.models.enums import (
    ContentKind,
    ContentStatus,
    FaqStatus,
    MaterialCategory,
    PagePublishStatus,
)


def _is_test_account(name: str) -> bool:
    lowered = name.casefold()
    return any(term in lowered for term in ("测试", "验收", "test", "acceptance", "demo"))


def startup_materials(db: Session, project_id: uuid.UUID) -> dict:
    brand = db.scalar(
        select(BrandProfile).where(
            BrandProfile.project_id == project_id,
            BrandProfile.is_active.is_(True),
        )
    )
    domains = list(brand.owned_domains or []) if brand else []

    published_pages = db.scalar(
        select(func.count(PublicPage.id)).where(
            PublicPage.project_id == project_id,
            PublicPage.publish_status == PagePublishStatus.PUBLISHED,
        )
    ) or 0

    accounts = db.scalars(
        select(PublishAccount).where(
            PublishAccount.project_id == project_id,
            PublishAccount.is_active.is_(True),
        )
    ).all()
    account_total = len(accounts)
    test_accounts = [row for row in accounts if _is_test_account(row.account_name)]
    configured_accounts = [row for row in accounts if (row.credential_ref or "").strip()]
    real_accounts = [
        row for row in accounts if row not in test_accounts and (row.credential_ref or "").strip()
    ]

    route_masters = db.scalars(
        select(ContentItem).where(
            ContentItem.project_id == project_id,
            ContentItem.kind == ContentKind.MASTER,
            ContentItem.status == ContentStatus.APPROVED,
            ContentItem.title.contains("实训"),
        )
    ).all()
    route_outlines = [
        row
        for row in route_masters
        if "AIGC" in row.title or "大模型" in row.title
    ]

    cases = db.scalar(
        select(func.count(Material.id)).where(
            Material.project_id == project_id,
            Material.category == MaterialCategory.CASE,
        )
    ) or 0

    faq_published = db.scalar(
        select(func.count(Faq.id)).where(
            Faq.project_id == project_id,
            Faq.status == FaqStatus.PUBLISHED,
            Faq.deleted_at.is_(None),
        )
    ) or 0
    faq_draft = db.scalar(
        select(func.count(Faq.id)).where(
            Faq.project_id == project_id,
            Faq.status == FaqStatus.DRAFT,
            Faq.deleted_at.is_(None),
        )
    ) or 0

    missing: list[str] = []
    if not domains:
        missing.append("域名：品牌档案未登记自有域名")
    if published_pages == 0:
        missing.append("CMS：无已发布公开页")
    if not real_accounts:
        missing.append(
            f"平台账号：0 个可发布真实账号（登记 {account_total} 个，"
            f"测试账号 {len(test_accounts)} 个，有凭据 {len(configured_accounts)} 个）"
        )
    if len(route_outlines) < 2:
        missing.append(f"路线大纲：仅 {len(route_outlines)} 条（AIGC/大模型各需一条）")
    if cases < 1:
        missing.append("授权作品/脱敏案例：无案例素材")
    if faq_published < 1:
        missing.append("招生就业口径：无已发布 FAQ")
    if faq_draft:
        missing.append(f"招生就业口径：{faq_draft} 条 FAQ 仍为 draft，需确认公开口径")

    items = [
        {
            "key": "domain",
            "label": "域名",
            "status": "ready" if domains else "missing",
            "count": len(domains),
            "detail": "、".join(domains) if domains else "品牌档案未登记",
        },
        {
            "key": "cms",
            "label": "CMS 公开页",
            "status": "ready" if published_pages else "missing",
            "count": published_pages,
            "detail": f"已发布 {published_pages} 页",
        },
        {
            "key": "platform_accounts",
            "label": "平台账号",
            "status": "ready" if real_accounts else ("partial" if account_total else "missing"),
            "count": len(real_accounts),
            "detail": (
                f"可发布真实账号 {len(real_accounts)} 个；登记 {account_total} 个，"
                f"测试 {len(test_accounts)} 个，有凭据 {len(configured_accounts)} 个"
            ),
        },
        {
            "key": "route_outlines",
            "label": "两条路线大纲",
            "status": "ready" if len(route_outlines) >= 2 else "missing",
            "count": len(route_outlines),
            "detail": "；".join(row.title for row in route_outlines) or "未找到 AIGC/大模型路线母稿",
        },
        {
            "key": "authorized_cases",
            "label": "授权作品/脱敏案例",
            "status": "ready" if cases else "missing",
            "count": cases,
            "detail": f"案例素材 {cases} 件",
        },
        {
            "key": "enrollment_faq",
            "label": "招生就业口径",
            "status": "ready" if faq_published else "missing",
            "count": faq_published,
            "detail": f"已发布 {faq_published} 条，draft {faq_draft} 条",
        },
    ]
    return {
        "ready": not missing,
        "missing": missing,
        "items": items,
        "generated_at": datetime.now(timezone.utc),
    }

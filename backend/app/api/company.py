"""企业档案接口：对标同类 GEO 平台的「基础信息 / 企业智能体画像」。

三条设计口径：

1. 用 PUT 做 upsert，前端不用判断「新建还是修改」——与 brand-profile 一致；
2. 保存前与 `facts` 做交叉校验：电话、成立日期这类可核验值若与权威事实不一致，
   必须带 `acknowledged_conflicts` 显式确认才允许写入，避免生产端复制错误；
3. 返回 `completeness / missing`，让前端直接显示「档案完整度」，不必自己算规则。

字段归属（与品牌设置的分工）：官网域名只有「品牌设置 → 自有域名」一个写入口，
本档案的 `official_urls` 是只读派生值，PUT 里出现非空官网地址直接拒绝，
避免同一个域名两处各存一份、改一处另一处还是旧值。
"""

import re
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, CompanyProfileData, Envelope, ok
from app.core.errors import AppError, ConflictError
from app.db.session import get_db
from app.models import BrandProfile, CompanyProfile, Fact
from app.models.company import CompanyProfileView
from app.models.enums import FactType
from app.schemas import CompanyProfileUpsert, CompanyProfileViewsUpsert
from app.services.audit import record_audit
from app.services.queries import fetch_many, fetch_one, fetch_one_for_update
from app.services.company_profile import (
    REQUIRED_FIELDS,
    brand_domains as _brand_domains,
    serialize_profile as _serialize,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/company-profile",
    tags=["企业档案"],
    responses=COMMON_ERRORS,
)

# 完整度规则与序列化都由 services/company_profile 提供：同一口径给档案页和投喂预检共用，
# 这里不再自己算一遍（历史上这里是唯一实现，预检反向 import api 才拿到了同一份）。
PHONE_KEYS = ("电话", "手机", "热线", "联系方式", "contact", "phone")
FOUNDED_KEYS = ("成立", "创办", "founded", "found")


def _digits(value: str | None) -> str:
    return re.sub(r"[^0-9]", "", value or "")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"([0-9]{4})[-/.年]([0-9]{1,2})(?:[-/.月]([0-9]{1,2}))?", value)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    day = int(match.group(3)) if match.group(3) else 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _fact_conflicts(db: Session, project_id, payload: CompanyProfileUpsert) -> list[dict]:
    """与 facts 的可核验值比对。只比对能确定语义的三类，不做模糊匹配。"""
    conflicts: list[dict] = []
    facts = fetch_many(
        db,
        Fact,
        [
            Fact.project_id == project_id,
            Fact.fact_type.in_([FactType.CONTACT, FactType.ORGANIZATION]),
            Fact.superseded_by.is_(None),
        ],
    )

    for fact in facts:
        if fact.fact_type == FactType.CONTACT:
            key = (fact.fact_key or "").casefold()
            if not any(token in key for token in PHONE_KEYS):
                continue
            fact_digits = _digits(fact.fact_value)
            if not fact_digits:
                continue
            for field in ("business_phone", "service_hotline"):
                value = getattr(payload, field)
                if not value or not _digits(value):
                    continue
                if _digits(value) != fact_digits:
                    conflicts.append(
                        {
                            "field": field,
                            "profile_value": value,
                            "fact_id": str(fact.id),
                            "fact_key": fact.fact_key,
                            "fact_value": fact.fact_value,
                        }
                    )
        elif fact.fact_type == FactType.ORGANIZATION:
            key = (fact.fact_key or "").casefold()
            if not any(token in key for token in FOUNDED_KEYS):
                continue
            if payload.founded_on is None:
                continue
            fact_date = _parse_date(fact.fact_value)
            if fact_date is None:
                continue
            if fact_date != payload.founded_on:
                conflicts.append(
                    {
                        "field": "founded_on",
                        "profile_value": payload.founded_on.isoformat(),
                        "fact_id": str(fact.id),
                        "fact_key": fact.fact_key,
                        "fact_value": fact.fact_value,
                    }
                )
    return conflicts


def _conflict_keys(conflicts: list[dict]) -> list[str]:
    return [f"{item['field']}:{item['fact_id']}" for item in conflicts]


def _load_views(db: Session, project_id) -> list[CompanyProfileView]:
    return fetch_many(db, CompanyProfileView, [CompanyProfileView.project_id == project_id])


@router.get("", response_model=Envelope[CompanyProfileData])
def get_company_profile(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
) -> dict:
    profile = fetch_one(db, CompanyProfile, project_id=ctx.project.id)
    return ok(
        _serialize(
            profile,
            domains=_brand_domains(db, ctx.project.id),
            views=_load_views(db, ctx.project.id),
        )
    )


@router.put("", response_model=Envelope[CompanyProfileData])
def upsert_company_profile(
    payload: CompanyProfileUpsert,
    ctx: ProjectContext = Depends(require_permission("brand.manage")),
    db: Session = Depends(get_db),
) -> dict:
    conflicts = _fact_conflicts(db, ctx.project.id, payload)
    if payload.official_urls:
        raise AppError(
            "官网域名只在「品牌设置 → 自有域名」维护，企业档案里只读展示；"
            "请到品牌设置修改后再回到本页查看",
            code="official_urls_readonly",
        )
    acknowledged = set(payload.acknowledged_conflicts)
    unacknowledged = [item for item in conflicts if f"{item['field']}:{item['fact_id']}" not in acknowledged]
    if unacknowledged:
        detail = "；".join(
            f"{item['field']} 填的是 {item['profile_value']}，权威事实（{item['fact_key']}）是 {item['fact_value']}"
            for item in unacknowledged
        )
        raise AppError(
            f"档案与权威事实冲突，需先确认：{detail}。确认后把 "
            f"{_conflict_keys(unacknowledged)} 放进 acknowledged_conflicts 再保存",
            code="company_fact_conflict",
        )

    profile = fetch_one_for_update(db, CompanyProfile, project_id=ctx.project.id)
    before = (
        {
            "legal_name": profile.legal_name,
            "brand_name": profile.brand_name,
            "description": profile.description,
            "is_active": profile.is_active,
        }
        if profile
        else None
    )
    if profile is None:
        profile = CompanyProfile(project_id=ctx.project.id)
        db.add(profile)

    profile.legal_name = payload.legal_name
    profile.brand_name = payload.brand_name
    profile.slogan = payload.slogan
    profile.province = payload.province
    profile.headcount = payload.headcount
    profile.founded_on = payload.founded_on
    profile.business_phone = payload.business_phone
    profile.service_hotline = payload.service_hotline
    profile.contact_email = payload.contact_email
    profile.stores = payload.stores or []
    # official_urls 不在此处落库：它是品牌设置自有域名的派生只读值。
    profile.industries = payload.industries or []
    profile.regions = payload.regions or []
    profile.products = [item.model_dump() for item in (payload.products or [])]
    profile.description = payload.description
    profile.highlights = payload.highlights
    profile.pain_points = payload.pain_points
    profile.story = payload.story
    profile.founder_intro = payload.founder_intro
    profile.extra = payload.extra
    profile.is_active = payload.is_active

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("企业档案并发写入冲突，请重试", code="company_profile_conflict") from exc

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="company.profile.upsert",
        target_type="company_profile",
        target_id=profile.id,
        payload={
            "before": before,
            "after": {
                "legal_name": profile.legal_name,
                "brand_name": profile.brand_name,
                "completeness": _serialize(profile, domains=_brand_domains(db, ctx.project.id))["completeness"],
                "is_active": profile.is_active,
            },
            # 显式记下「哪些冲突被人工确认过」，事后可复盘是谁认了哪个数。
            "acknowledged_conflicts": sorted(acknowledged),
        },
    )
    db.commit()
    db.refresh(profile)
    return ok(
        _serialize(
            profile,
            conflicts,
            domains=_brand_domains(db, ctx.project.id),
            views=_load_views(db, ctx.project.id),
        )
    )


@router.put("/views", response_model=Envelope[CompanyProfileData])
def upsert_company_profile_views(
    payload: CompanyProfileViewsUpsert,
    ctx: ProjectContext = Depends(require_permission("brand.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """按 kind 覆盖四套对外画像。只动传进来的那几套，没传的保持原样。"""
    existing = {row.kind: row for row in _load_views(db, ctx.project.id)}
    changed: list[str] = []
    for item in payload.views:
        row = existing.get(item.kind)
        if row is None:
            row = CompanyProfileView(project_id=ctx.project.id, kind=item.kind)
            db.add(row)
        row.title = item.title
        row.audience = item.audience
        row.scenario_words = item.scenario_words or []
        row.description = item.description
        row.cautions = item.cautions
        row.is_active = item.is_active
        changed.append(item.kind)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("对外画像并发写入冲突，请重试", code="company_view_conflict") from exc

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="company.profile.views.upsert",
        target_type="company_profile_view",
        payload={
            "kinds": sorted(changed),
            # 只记结构信息：四套说法的正文可能很长，审计里留摘要就够复盘。
            "summary": {
                item.kind: {
                    "configured": bool(item.description or item.title or item.audience),
                    "scenario_words": len(item.scenario_words or []),
                    "is_active": item.is_active,
                }
                for item in payload.views
            },
            "view_count": len(changed),
        },
    )
    db.commit()
    return ok(
        _serialize(
            fetch_one(db, CompanyProfile, project_id=ctx.project.id),
            domains=_brand_domains(db, ctx.project.id),
            views=_load_views(db, ctx.project.id),
        )
    )
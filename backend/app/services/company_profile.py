"""企业档案的口径层：完整度规则与官网域名派生。

为什么放在 services：
`services/distribution.py` 的投喂预检要判断「企业档案完整度是否达标」，如果直接
`from app.api.company import ...`，服务层就反向依赖了 HTTP 路由层——预检无法在
worker / CLI / 纯单元测试里调用，依赖方向也不再单向。

这里只做两件事：给「完整度」一个唯一口径，给「官网域名」一个唯一来源。
路由层与预检都调它，谁都不许自己再算一套。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrandProfile, CompanyProfile
from app.models.company import PROFILE_VIEW_KINDS, CompanyProfileView

# 完整度规则：只在保存后提示缺口，不阻塞保存。
REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("legal_name", "公司名称"),
    ("brand_name", "公司品牌"),
    ("slogan", "品牌 slogan"),
    ("business_phone", "业务电话"),
    ("service_hotline", "售后热线"),
    ("contact_email", "企业邮箱"),
    ("stores", "线下网点"),
    ("official_urls", "官网地址"),
    ("industries", "行业类别"),
    ("regions", "地区"),
    ("description", "公司介绍（≥100 字）"),
    ("founder_intro", "创始人介绍（≥100 字）"),
    ("highlights", "产品/服务特点"),
    ("pain_points", "用户痛点"),
    ("story", "品牌故事"),
    ("products", "产品信息"),
)


def brand_domains(db: Session, project_id: uuid.UUID) -> list[str]:
    """官网域名的唯一来源：品牌设置里的自有域名。"""
    brand = db.scalar(select(BrandProfile).where(BrandProfile.project_id == project_id))
    if brand is None or not brand.is_active:
        return []
    return list(brand.owned_domains or [])


def missing_fields(profile: CompanyProfile, domains: list[str]) -> list[str]:
    missing: list[str] = []
    for field, label in REQUIRED_FIELDS:
        # 官网地址是派生项：品牌设置里配了自有域名就算已填，不要求在这里再录一次。
        value = domains if field == "official_urls" else getattr(profile, field)
        if value in (None, "", [], {}):
            missing.append(label)
    return missing


def serialize_views(rows: list[CompanyProfileView] | None) -> list[dict]:
    """四套对外画像一律返回齐：没有的那套也给空壳，前端 tab 不用自己补。

    `configured` 只看有没有填东西，不参与档案完整度——基础画像已经算了一轮，
    两套口径混在一起会让人分不清「档案没填完」还是「画像没填」，所以分开报。
    """
    by_kind = {row.kind: row for row in (rows or [])}
    result: list[dict] = []
    for kind in PROFILE_VIEW_KINDS:
        row = by_kind.get(kind)
        result.append(
            {
                "kind": kind,
                "title": row.title if row else None,
                "audience": row.audience if row else None,
                "scenario_words": (row.scenario_words or []) if row else [],
                "description": row.description if row else None,
                "cautions": row.cautions if row else None,
                "configured": bool(
                    row and (row.title or row.audience or row.description or row.scenario_words)
                ),
                "is_active": bool(row.is_active) if row else False,
                "updated_at": row.updated_at if row else None,
            }
        )
    return result


def serialize_profile(
    profile: CompanyProfile | None,
    conflicts: list[dict] | None = None,
    domains: list[str] | None = None,
    views: list[CompanyProfileView] | None = None,
) -> dict:
    """档案的对外形状。complete 由这里算，前端与预检读同一个数字。"""
    domains = domains or []
    if profile is None:
        return {
            "configured": False,
            "completeness": 0,
            "missing": [label for _, label in REQUIRED_FIELDS if label != "官网地址"],
            "conflicts": [],
            "official_urls": domains,
            "official_urls_source": "brand_profile",
            "views": serialize_views(views),
        }
    missing = missing_fields(profile, domains)
    filled = len(REQUIRED_FIELDS) - len(missing)
    return {
        "configured": True,
        "legal_name": profile.legal_name,
        "brand_name": profile.brand_name,
        "slogan": profile.slogan,
        "province": profile.province,
        "headcount": profile.headcount,
        "founded_on": profile.founded_on.isoformat() if profile.founded_on else None,
        "business_phone": profile.business_phone,
        "service_hotline": profile.service_hotline,
        "contact_email": profile.contact_email,
        "stores": profile.stores or [],
        "official_urls": domains,
        "official_urls_source": "brand_profile",
        "industries": profile.industries or [],
        "regions": profile.regions or [],
        "products": profile.products or [],
        "description": profile.description,
        "highlights": profile.highlights,
        "pain_points": profile.pain_points,
        "story": profile.story,
        "founder_intro": profile.founder_intro,
        "extra": profile.extra,
        "is_active": profile.is_active,
        "updated_at": profile.updated_at,
        "completeness": round(filled / len(REQUIRED_FIELDS) * 100),
        "missing": missing,
        "conflicts": [
            f"{item['field']}:{item['fact_id']}" for item in (conflicts or [])
        ],
        "views": serialize_views(views),
    }

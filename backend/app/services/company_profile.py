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


def serialize_profile(
    profile: CompanyProfile | None,
    conflicts: list[dict] | None = None,
    domains: list[str] | None = None,
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
    }

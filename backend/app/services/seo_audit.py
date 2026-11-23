"""页面 SEO 核验：只查「有没有」，不做排名预测、不给分数。

两个入口：
- `audit_html(html, required)`：任意页面 HTML（微站、官网落地页、客户站），查必备标签；
- `microsite_seo_report(db, project_id, ...)`：按微站数据推导**将渲染出的 head 字段**，
  在站还没上线时也能核验，避免「上线后才发现缺 og:image」。

必备标签清单来自项目口径 `seo.required_tags`，通用默认八项；项目可增删。
图片取站内模块里第一个可访问的图片 URL——没有图就如实报缺，不拿占位图凑数。
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.microsite import SiteModule, SiteSite
from app.services.project_policy import policy_value

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")

# HTML 侧检测规则：一个标签一条正则，命中即视为存在（值可为空也算「有标签」，只有空值另报）
HTML_PATTERNS = {
    "canonical": re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]*>', re.I),
    "description": re.compile(r'<meta[^>]+name=["\']description["\'][^>]*content=["\'][^"\']+', re.I),
    "og:title": re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\'][^"\']+', re.I),
    "og:description": re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]*content=["\'][^"\']+', re.I),
    "og:image": re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\'][^"\']+', re.I),
    "og:url": re.compile(r'<meta[^>]+property=["\']og:url["\'][^>]*content=["\'][^"\']+', re.I),
    "twitter:card": re.compile(r'<meta[^>]+name=["\']twitter:card["\'][^>]*content=["\'][^"\']+', re.I),
    "json-ld": re.compile(r'<script[^>]+type=["\']application/ld\+json["\']', re.I),
}


def audit_html(html: str, required: list[str] | None = None) -> dict:
    required = required or policy_value_list_default()
    present = [tag for tag in required if _pattern_for(tag).search(html)]
    missing = [tag for tag in required if tag not in present]
    return {
        "required": required,
        "present": present,
        "missing": missing,
        "ok": not missing,
        "note": "只判标签存在与是否为空，不看关键词密度、不做排名预测；未知标签按缺失处理。",
    }


def policy_value_list_default() -> list[str]:
    from app.services.project_policy import DEFAULTS

    return list(DEFAULTS["seo.required_tags"])


def _pattern_for(tag: str) -> re.Pattern[str]:
    pattern = HTML_PATTERNS.get(tag)
    if pattern is not None:
        return pattern
    # 未知标签：按 `name=`/`property=` 通用形式匹配，找不到就报缺失
    return re.compile(rf'<meta[^>]+(?:name|property)=["\']{re.escape(tag)}["\'][^>]*content=["\'][^"\']+', re.I)


def _first_image(node, depth: int = 0):
    if depth > 5:
        return None
    if isinstance(node, str):
        return node if node.lower().split("?")[0].endswith(IMAGE_EXT) and node.startswith("http") else None
    if isinstance(node, dict):
        for value in node.values():
            found = _first_image(value, depth + 1)
            if found:
                return found
        return None
    if isinstance(node, list):
        for value in node:
            found = _first_image(value, depth + 1)
            if found:
                return found
    return None


def _site_field_values(site: SiteSite, modules: list[SiteModule]) -> dict[str, str]:
    image = None
    for module in modules:
        if not module.is_active:
            continue
        image = _first_image(module.content)
        if image:
            break
    values = {
        "canonical": f"/s/{site.slug}",
        "description": (site.intro or "").strip(),
        "og:title": site.title,
        "og:description": (site.intro or "").strip(),
        "og:url": f"/s/{site.slug}",
        "og:image": image or "",
        "twitter:card": "summary_large_image" if image else "summary",
        "json-ld": "Organization",
    }
    return values


def microsite_seo_report(
    db: Session,
    project_id: uuid.UUID,
    *,
    slug: str | None = None,
    required: list[str] | None = None,
) -> dict:
    required = required or list(policy_value(db, project_id, "seo.required_tags"))
    query = select(SiteSite).where(SiteSite.project_id == project_id)
    if slug:
        query = query.where(SiteSite.slug == slug)
    sites = list(db.scalars(query))
    if not sites:
        return {
            "required": required,
            "sites": [],
            "missing": required,
            "ok": False,
            "note": "该项目还没有微站实例（site_sites 为空）；能力已就绪，站建好后本接口直接可用。",
        }
    results = []
    for site in sites:
        modules = list(db.scalars(select(SiteModule).where(SiteModule.site_id == site.id)))
        values = _site_field_values(site, modules)
        missing = [tag for tag in required if not values.get(tag)]
        results.append({
            "slug": site.slug,
            "is_published": site.is_published,
            "values": {tag: values.get(tag, "") for tag in required},
            "present": [tag for tag in required if values.get(tag)],
            "missing": missing,
            "ok": not missing,
        })
    missing_all = sorted({tag for item in results for tag in item["missing"]})
    return {
        "required": required,
        "sites": results,
        "missing": missing_all,
        "ok": not missing_all,
        "note": "head 字段按站内数据推导；og:image 取模块里第一个可访问图片，无图即报缺。",
    }

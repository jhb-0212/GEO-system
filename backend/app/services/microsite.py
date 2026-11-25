"""K8 微站：项目级站点装配。

口径：
- 一个项目一个站，slug 默认取项目 code（已存在时自动加序号），保证公开链接可读；
- 站内固定 6 个模块，每种一条，未启用的模块不进公开渲染；
- 模块正文是 JSON，只做体积限制（单模块 ≤ 20KB），不猜业务字段——渲染层按类型取字段，
  后台填错字段最多是那一段不显示，不会 500。
"""

from __future__ import annotations

import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, BusinessValidationError
from app.models import SiteModule, SiteSite
from app.models.enums import SiteModuleType
from app.services.branding import organization_branding

CONTENT_LIMIT = 20_000

# 6 个模块的默认文案与空内容骨架：后台打开就能看到「该填什么」，不用读文档
MODULE_SEEDS: tuple[tuple[SiteModuleType, str, dict], ...] = (
    (
        SiteModuleType.HOME,
        "首页",
        {"headline": "", "paragraphs": [], "links": []},
    ),
    (
        SiteModuleType.SERVICES,
        "产品服务",
        {"items": [{"name": "", "desc": ""}]},
    ),
    (
        SiteModuleType.NEWS,
        "资讯",
        {"items": [{"title": "", "url": "", "date": ""}]},
    ),
    (
        SiteModuleType.DOWNLOAD,
        "PDF 资料",
        {"items": [{"name": "", "url": ""}]},
    ),
    (
        SiteModuleType.POSTER,
        "海报",
        {"items": [{"title": "", "image_url": ""}]},
    ),
    (
        SiteModuleType.CARD,
        "名片",
        {"name": "", "role": "", "phone": "", "wechat": "", "qrcode_url": ""},
    ),
)

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def slugify(value: str) -> str:
    """统一小写、只留字母数字与连字符，避免 URL 里出现中文或空格。"""
    cleaned = _SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")
    return cleaned or "site"


def validate_content(content: dict) -> None:
    if not isinstance(content, dict):
        raise BusinessValidationError("模块内容必须是 JSON 对象", code="site_content_invalid")
    size = len(json.dumps(content, ensure_ascii=False))
    if size > CONTENT_LIMIT:
        raise BusinessValidationError(
            f"模块内容过长（{size} 字符，上限 {CONTENT_LIMIT}）", code="site_content_too_large"
        )


def ensure_site(db: Session, project_id: uuid.UUID, project_code: str, project_name: str) -> SiteSite:
    """取或建站：第一次访问后台就自动建好 6 个模块，省掉「先建站再建模块」的空转。"""
    site = db.scalar(select(SiteSite).where(SiteSite.project_id == project_id))
    if site is None:
        base = slugify(project_code)
        slug = base
        suffix = 2
        while db.scalar(select(SiteSite.id).where(SiteSite.slug == slug)) is not None:
            slug = f"{base}-{suffix}"
            suffix += 1
        site = SiteSite(
            project_id=project_id,
            slug=slug,
            title=project_name,
            intro=None,
            is_published=False,
        )
        db.add(site)
        db.flush()

    existing = {
        row.module_type
        for row in db.execute(
            select(SiteModule).where(SiteModule.site_id == site.id)
        ).scalars().all()
    }
    for index, (module_type, title, content) in enumerate(MODULE_SEEDS):
        if module_type in existing:
            continue
        db.add(
            SiteModule(
                project_id=project_id,
                site_id=site.id,
                module_type=module_type,
                title=title,
                content=content,
                sort_order=index,
                is_active=module_type is SiteModuleType.HOME,
            )
        )
    db.flush()
    return site


def modules_of(db: Session, site_id: uuid.UUID) -> list[SiteModule]:
    return list(
        db.execute(
            select(SiteModule)
            .where(SiteModule.site_id == site_id)
            .order_by(SiteModule.sort_order.asc(), SiteModule.module_type.asc())
        ).scalars().all()
    )


def site_snapshot(db: Session, site: SiteSite) -> dict:
    return {
        "slug": site.slug,
        "title": site.title,
        "intro": site.intro,
        "is_published": site.is_published,
        "modules": [
            {
                "id": str(module.id),
                "module_type": module.module_type.value,
                "title": module.title,
                "content": module.content,
                "sort_order": module.sort_order,
                "is_active": module.is_active,
            }
            for module in modules_of(db, site.id)
        ],
    }


def public_snapshot(db: Session, slug: str) -> dict | None:
    """公开视图：未发布或 slug 不存在都返回 None，调用方统一给 404，不泄露「这个站存在但没发」。"""
    site = db.scalar(select(SiteSite).where(SiteSite.slug == slug))
    if site is None or not site.is_published:
        return None
    active = [module for module in modules_of(db, site.id) if module.is_active]
    branding = organization_branding(db, site.project_id)
    return {
        "slug": site.slug,
        "title": site.title,
        "intro": site.intro,
        "branding": branding,
        "modules": [
            {
                "module_type": module.module_type.value,
                "title": module.title,
                "content": module.content,
            }
            for module in active
        ],
    }


def assert_slug_free(db: Session, slug: str, project_id: uuid.UUID) -> None:
    other = db.scalar(
        select(SiteSite).where(SiteSite.slug == slug, SiteSite.project_id != project_id)
    )
    if other is not None:
        raise ConflictError("这个访问路径已被其他项目占用", code="site_slug_taken")

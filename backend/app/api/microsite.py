"""K8 微站配置接口：GET 会自动建站（幂等），PATCH 只管开关与内容。

为什么要 GET 时建：微站是「开了才有用」的页面，先进页面看到 6 个空模块比先点「创建」更直观；
建站只发生在该项目第一次访问，之后都是纯读，不会每次 GET 都写库。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.db.session import get_db
from app.services.queries import fetch_one
from app.models import SiteModule
from app.models.enums import SiteModuleType
from app.schemas.microsite import SiteModuleUpdate, SiteUpdate
from app.services.audit import record_audit
from app.services.microsite import (
    assert_slug_free,
    ensure_site,
    site_snapshot,
    slugify,
    validate_content,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/site",
    tags=["微站"],
    responses=COMMON_ERRORS,
)


def _get_site(db: Session, ctx: ProjectContext):
    return ensure_site(db, ctx.project.id, ctx.project.code, ctx.project.name)


@router.get("", response_model=Envelope[dict])
def get_site(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    site = _get_site(db, ctx)
    db.commit()
    return ok(site_snapshot(db, site))


@router.patch("", response_model=Envelope[dict])
def update_site(
    payload: SiteUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    site = _get_site(db, ctx)
    changes = payload.model_dump(exclude_unset=True)
    if "slug" in changes:
        new_slug = slugify(changes["slug"] or "")
        assert_slug_free(db, new_slug, ctx.project.id)
        changes["slug"] = new_slug
    if "title" in changes and not (changes["title"] or "").strip():
        changes.pop("title")
    for field, value in changes.items():
        setattr(site, field, value)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="site.update",
        target_type="site",
        target_id=site.id,
        payload={"fields": sorted(changes), "is_published": site.is_published},
    )
    db.commit()
    return ok(site_snapshot(db, site))


@router.patch("/modules/{module_type}", response_model=Envelope[dict])
def update_module(
    module_type: SiteModuleType,
    payload: SiteModuleUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    site = _get_site(db, ctx)
    module = fetch_one(
        db, SiteModule, site_id=site.id, module_type=module_type
    )
    if module is None:  # 理论上 ensure_site 已补齐，留作防御
        raise AssertionError("模块缺失，ensure_site 未补齐 6 个模块")
    changes = payload.model_dump(exclude_unset=True)
    if "content" in changes:
        validate_content(changes["content"])
    for field, value in changes.items():
        setattr(module, field, value)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="site.module.update",
        target_type="site_module",
        target_id=module.id,
        payload={"module_type": module_type.value, "fields": sorted(changes)},
    )
    db.commit()
    return ok(site_snapshot(db, site))

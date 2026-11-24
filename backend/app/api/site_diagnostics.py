"""官网 AI 爬虫诊断与访问观测接口。

L1 检查由系统发起；L2/L3 只接受官网/CDN 日志导入，不把 UA 声明直接当作真实爬虫。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.core.errors import ResourceMissingError
from app.db.session import get_db
from app.services.queries import fetch_many, fetch_one
from app.models import PublicPage
from app.schemas.site_diagnostics import (
    CrawlerEventImport,
    CrawlerEventImportResult,
    PageCheckBatch,
    PageCheckBatchResult,
    PageCheckResult,
    SiteDiagnosticsSummary,
    TrafficEventImport,
    TrafficEventImportResult,
)
from app.services.audit import record_audit
from app.services.site_diagnostics import (
    check_public_page,
    import_crawler_events,
    import_traffic_events,
    site_diagnostics_summary,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["官网诊断"],
    responses=COMMON_ERRORS,
)


def _get_page(db: Session, project_id: uuid.UUID, page_id: uuid.UUID) -> PublicPage:
    page = fetch_one(db, PublicPage, project_id=project_id, id=page_id)
    if page is None:
        raise ResourceMissingError("公开站页面不存在", code="page_missing")
    return page


@router.post("/pages/{page_id}/check", response_model=Envelope[PageCheckResult])
def check_page(
    page_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    page = _get_page(db, ctx.project.id, page_id)
    result = check_public_page(page)
    for key, value in result.items():
        setattr(page, key, value)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="page.check",
        target_type="public_page",
        target_id=page.id,
        payload={
            "url": page.url,
            "http_status": result["http_status"],
            "robots_allowed": result["robots_allowed"],
            "in_sitemap": result["in_sitemap"],
            "canonical_ok": result["canonical_ok"],
            "js_dependent": result["js_dependent"],
            "check_error": result["check_error"],
        },
    )
    db.commit()
    return ok(
        {
            "id": str(page.id),
            "url": page.url,
            "canonical_url": page.canonical_url,
            **result,
        }
    )


@router.get("/site-diagnostics", response_model=Envelope[SiteDiagnosticsSummary])
def diagnostics_summary(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    return ok(site_diagnostics_summary(db, ctx.project.id))


@router.post("/pages/check-batch", response_model=Envelope[PageCheckBatchResult])
def check_pages_batch(
    payload: PageCheckBatch,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    """按页 ID 批量检查 L1；单次最多 20 页，由前端分批循环。

    单页抓取失败仍写入该页 check_error，不阻断同一批其他页面；
    整批只写一条审计，避免一次全量检查产生 69 条 page.check 噪声。
    """
    page_ids = list(dict.fromkeys(payload.page_ids))
    rows = fetch_many(
        db,
        PublicPage,
        [
            PublicPage.project_id == ctx.project.id,
            PublicPage.id.in_(page_ids),
        ],
    )
    page_by_id = {page.id: page for page in rows}
    missing = [page_id for page_id in page_ids if page_id not in page_by_id]
    if missing:
        raise ResourceMissingError(
            f"有 {len(missing)} 个页面不属于当前项目或已删除",
            code="page_missing",
        )

    items: list[dict] = []
    for page_id in page_ids:
        page = page_by_id[page_id]
        result = check_public_page(page)
        for key, value in result.items():
            setattr(page, key, value)
        items.append(
            {
                "id": str(page.id),
                "url": page.url,
                "canonical_url": page.canonical_url,
                **result,
            }
        )

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="page.check_batch",
        target_type="public_page_batch",
        payload={
            "checked": len(items),
            "errors": sum(1 for item in items if item["check_error"]),
            "page_ids": [str(item["id"]) for item in items],
        },
    )
    db.commit()
    return ok(
        {
            "checked": len(items),
            "errors": sum(1 for item in items if item["check_error"]),
            "items": items,
        }
    )


@router.post("/crawler-events/import", response_model=Envelope[CrawlerEventImportResult])
def import_crawler_log(
    payload: CrawlerEventImport,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    imported, matched_pages = import_crawler_events(
        db,
        ctx.project.id,
        [item.model_dump() for item in payload.events],
        payload.source,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="crawler_events.import",
        target_type="crawler_event",
        payload={"imported": imported, "matched_pages": matched_pages, "source": payload.source},
    )
    db.commit()
    return ok({"imported": imported, "matched_pages": matched_pages})


@router.post("/traffic-events/import", response_model=Envelope[TrafficEventImportResult])
def import_traffic_log(
    payload: TrafficEventImport,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    imported = import_traffic_events(
        db,
        ctx.project.id,
        [item.model_dump() for item in payload.events],
        payload.source,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="traffic_events.import",
        target_type="traffic_event",
        payload={"imported": imported, "source": payload.source},
    )
    db.commit()
    return ok({"imported": imported})

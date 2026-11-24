"""公开站事实页登记：只做后端台账，不生成页面、不发布站点。

slug 项目内唯一且创建后不可改；A 侧公开站上线后按 url/canonical_url 对外服务。
"""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, PageCreated, PageData, ok, ok_page
from app.core.errors import AppError, ConflictError, ResourceMissingError
from app.db.session import get_db
from app.models import ContentItem, PublicPage
from app.models.enums import PagePublishStatus, PageType
from app.schemas import PageCreate, PageUpdate
from app.services.page_registry import (
    list_pages as _list_page_rows,
    page_payload as _page_data,
    page_row as _get_page,
    slug_exists,
)
from app.services.references import require_project_row_id
from app.services.state_machine import ensure_page_publish_transition
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/pages",
    tags=["公开站页面"],
    responses=COMMON_ERRORS,
)


@router.get("", response_model=PagedEnvelope[PageData])
def list_pages(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    publish_status: PagePublishStatus | None = None,
    page_type: PageType | None = None,
    slug: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    total, rows = _list_page_rows(
        db,
        ctx.project.id,
        publish_status=publish_status,
        page_type=page_type,
        slug=slug,
        page=page,
        page_size=page_size,
    )
    return ok_page(
        [_page_data(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[PageCreated])
def create_page(
    payload: PageCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    require_project_row_id(
        db, ContentItem, ctx.project.id, payload.content_item_id,
        label="内容", code="content_item_missing",
    )
    if slug_exists(db, ctx.project.id, payload.slug):
        raise ConflictError("slug 已存在", code="page_slug_conflict")

    page = PublicPage(
        project_id=ctx.project.id,
        slug=payload.slug,
        title=payload.title,
        page_type=payload.page_type,
        url=payload.url,
        canonical_url=payload.canonical_url,
        publish_status=payload.publish_status,
        content_item_id=payload.content_item_id,
        last_published_at=datetime.now(timezone.utc) if payload.publish_status == PagePublishStatus.PUBLISHED else None,
    )
    db.add(page)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("slug 已存在", code="page_slug_conflict") from exc

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="page.create",
        target_type="public_page",
        target_id=page.id,
        payload={"slug": page.slug, "page_type": page.page_type.value, "publish_status": page.publish_status.value},
    )
    db.commit()
    return ok({"id": str(page.id), "slug": page.slug})


@router.patch("/{page_id}", response_model=Envelope[PageData])
def update_page(
    page_id: uuid.UUID,
    payload: PageUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    page = _get_page(db, ctx.project.id, page_id, for_update=True)
    changes = payload.model_dump(exclude_unset=True)
    for field in ("title", "page_type", "url"):
        if field in changes and changes[field] is None:
            raise AppError(f"{field} 不能为空", code="invalid_page_update")
    if "content_item_id" in changes:
        require_project_row_id(
            db, ContentItem, ctx.project.id, changes["content_item_id"],
            label="内容", code="content_item_missing",
        )

    if "publish_status" in changes:
        changes["publish_status"] = ensure_page_publish_transition(
            page.publish_status, changes["publish_status"]
        )

    audit_changes: dict[str, object] = {}
    for key, value in changes.items():
        setattr(page, key, value)
        if isinstance(value, uuid.UUID):
            audit_changes[key] = str(value)
        elif hasattr(value, "value"):
            audit_changes[key] = value.value
        else:
            audit_changes[key] = value
    if changes.get("publish_status") == PagePublishStatus.PUBLISHED:
        page.last_published_at = datetime.now(timezone.utc)

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="page.update",
        target_type="public_page",
        target_id=page.id,
        payload={"changes": audit_changes},
    )
    db.commit()
    return ok(_page_data(page))

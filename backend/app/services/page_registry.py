"""公开站页面台账的读取与查重，从 `api/pages.py` 下沉。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import PublicPage
from app.models.enums import PagePublishStatus, PageType


def page_row(
    db: Session, project_id: uuid.UUID, page_id: uuid.UUID, *, for_update: bool = False
) -> PublicPage:
    query = select(PublicPage).where(
        PublicPage.project_id == project_id,
        PublicPage.id == page_id,
    )
    if for_update:
        query = query.with_for_update()
    page = db.scalar(query)
    if page is None:
        raise ResourceMissingError("公开站页面不存在", code="page_missing")
    return page


def slug_exists(db: Session, project_id: uuid.UUID, slug: str) -> bool:
    return (
        db.scalar(
            select(PublicPage.id).where(
                PublicPage.project_id == project_id,
                PublicPage.slug == slug,
            )
        )
        is not None
    )


def page_payload(page: PublicPage) -> dict:
    return {
        "id": str(page.id),
        "slug": page.slug,
        "title": page.title,
        "page_type": page.page_type.value,
        "url": page.url,
        "canonical_url": page.canonical_url,
        "publish_status": page.publish_status.value,
        "content_item_id": str(page.content_item_id) if page.content_item_id else None,
        "last_published_at": page.last_published_at,
        "robots_allowed": page.robots_allowed,
        "in_sitemap": page.in_sitemap,
        "canonical_ok": page.canonical_ok,
        "http_status": page.http_status,
        "js_dependent": page.js_dependent,
        "checked_at": page.checked_at,
        "check_error": page.check_error,
        "created_at": page.created_at,
        "updated_at": page.updated_at,
    }


def list_pages(
    db: Session,
    project_id: uuid.UUID,
    *,
    publish_status: PagePublishStatus | None,
    page_type: PageType | None,
    slug: str | None,
    page: int,
    page_size: int,
) -> tuple[int, list[PublicPage]]:
    filters = [PublicPage.project_id == project_id]
    if publish_status is not None:
        filters.append(PublicPage.publish_status == publish_status)
    if page_type is not None:
        filters.append(PublicPage.page_type == page_type)
    if slug is not None:
        filters.append(PublicPage.slug == slug)

    total = db.scalar(select(func.count()).select_from(PublicPage).where(*filters)) or 0
    rows = db.scalars(
        select(PublicPage)
        .where(*filters)
        .order_by(PublicPage.created_at.desc(), PublicPage.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return int(total), list(rows)

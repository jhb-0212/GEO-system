"""内容版本 / 审核记录 / 交付包所需的读取，从 `api/content.py` 下沉。

序列化仍留在 api（`content_status_label` 等展示口径属于响应层）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ContentItem, ContentReview, ContentVersion, ProjectContact, PublicPage, User
from app.models.enums import ContentFormat, ContentStatus


def page_versions(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: ContentStatus | None,
    page: int,
    page_size: int,
    content_type: ContentFormat | None = None,
    within_days: int | None = None,
) -> tuple[int, list[tuple[ContentVersion, ContentItem, str | None]]]:
    filters = [ContentVersion.project_id == project_id]
    if status is not None:
        filters.append(ContentVersion.status == status)
    if content_type is not None:
        filters.append(ContentItem.content_type == content_type)
    if within_days is not None:
        filters.append(
            ContentVersion.created_at
            >= datetime.now(timezone.utc) - timedelta(days=within_days)
        )
    if status == ContentStatus.PENDING_REVIEW:
        # 审核队列只列当前版本；历史遗留的非当前 pending_review 不再出现在队列里。
        filters.append(ContentVersion.id == ContentItem.current_version_id)

    total = (
        db.scalar(
            select(func.count())
            .select_from(ContentVersion)
            .join(ContentItem, ContentItem.id == ContentVersion.item_id)
            .where(*filters, ContentItem.project_id == project_id)
        )
        or 0
    )
    rows = db.execute(
        select(ContentVersion, ContentItem, User.display_name)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .outerjoin(
            User,
            User.id == func.coalesce(ContentVersion.submitted_by, ContentVersion.created_by),
        )
        .where(*filters, ContentItem.project_id == project_id)
        .order_by(
            ContentVersion.submitted_at.desc().nullslast(),
            ContentVersion.created_at.desc(),
            ContentVersion.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return int(total), [(row[0], row[1], row[2]) for row in rows]


def max_version_no(db: Session, item_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.max(ContentVersion.version_no)).where(
                ContentVersion.item_id == item_id
            )
        )
        or 0
    )


def known_phones(db: Session, project_id: uuid.UUID) -> set[str]:
    """对外渠道里登记过的号码：正文号码只有落在这一集合里才不提示。"""
    rows = db.scalars(
        select(ProjectContact.value).where(
            ProjectContact.project_id == project_id,
            ProjectContact.is_active.is_(True),
        )
    ).all()
    return {str(value).strip() for value in rows if value}


def page_reviews(
    db: Session,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
) -> tuple[int, list[tuple[ContentReview, str | None]]]:
    filters = [
        ContentReview.project_id == project_id,
        ContentReview.version_id == version_id,
    ]
    total = db.scalar(select(func.count()).select_from(ContentReview).where(*filters)) or 0
    rows = db.execute(
        select(ContentReview, User.display_name)
        .outerjoin(User, User.id == ContentReview.reviewer_id)
        .where(*filters)
        .order_by(ContentReview.created_at.desc(), ContentReview.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return int(total), [(row[0], row[1]) for row in rows]


def latest_public_page(
    db: Session, project_id: uuid.UUID, item_id: uuid.UUID
) -> PublicPage | None:
    """交付包里的 canonical：取该内容最近建的一页公开站页面。"""
    return db.scalar(
        select(PublicPage)
        .where(
            PublicPage.project_id == project_id,
            PublicPage.content_item_id == item_id,
        )
        .order_by(PublicPage.created_at.desc())
    )

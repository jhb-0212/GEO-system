"""运营计划的读取、关联校验与分页，从 `api/plans.py` 下沉。

列表页把负责人姓名改成一次批量取，避免每行一次查询。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import Channel, ContentItem, ContentPlan, ProjectMember, PublicPage, User
from app.models.enums import ContentPlanStatus, PlanType


def plan_row(
    db: Session, project_id: uuid.UUID, plan_id: uuid.UUID, *, for_update: bool = False
) -> ContentPlan:
    query = select(ContentPlan).where(
        ContentPlan.project_id == project_id,
        ContentPlan.id == plan_id,
    )
    if for_update:
        query = query.with_for_update()
    plan = db.scalar(query)
    if plan is None:
        raise ResourceMissingError("运营计划不存在", code="plan_missing")
    return plan


def ensure_channel(db: Session, project_id: uuid.UUID, channel_id: uuid.UUID | None) -> None:
    if channel_id is None:
        return
    if (
        db.scalar(
            select(Channel.id).where(
                Channel.project_id == project_id, Channel.id == channel_id
            )
        )
        is None
    ):
        raise ResourceMissingError("渠道不存在", code="channel_missing")


def ensure_content_item(
    db: Session, project_id: uuid.UUID, item_id: uuid.UUID | None
) -> None:
    if item_id is None:
        return
    if (
        db.scalar(
            select(ContentItem.id).where(
                ContentItem.project_id == project_id, ContentItem.id == item_id
            )
        )
        is None
    ):
        raise ResourceMissingError("内容不存在", code="content_item_missing")


def ensure_page(db: Session, project_id: uuid.UUID, page_id: uuid.UUID | None) -> None:
    if page_id is None:
        return
    if (
        db.scalar(
            select(PublicPage.id).where(
                PublicPage.project_id == project_id, PublicPage.id == page_id
            )
        )
        is None
    ):
        raise ResourceMissingError("公开站页面不存在", code="page_missing")


def ensure_owner(db: Session, project_id: uuid.UUID, owner_id: uuid.UUID | None) -> None:
    if owner_id is None:
        return
    member = db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == owner_id,
            ProjectMember.is_active.is_(True),
        )
    )
    if member is None:
        raise ResourceMissingError(
            "负责人不是当前项目的有效成员", code="owner_missing"
        )


def owner_names(db: Session, owner_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not owner_ids:
        return {}
    return {
        user_id: display_name
        for user_id, display_name in db.execute(
            select(User.id, User.display_name).where(User.id.in_(owner_ids))
        ).all()
    }


def plan_payload(plan: ContentPlan, *, owner_name: str | None) -> dict:
    return {
        "id": str(plan.id),
        "title": plan.title,
        "plan_type": plan.plan_type.value,
        "status": plan.status.value,
        "channel_id": str(plan.channel_id) if plan.channel_id else None,
        "content_item_id": str(plan.content_item_id) if plan.content_item_id else None,
        "site_page_id": str(plan.site_page_id) if plan.site_page_id else None,
        "owner_id": str(plan.owner_id) if plan.owner_id else None,
        "owner_name": owner_name,
        "scheduled_at": plan.scheduled_at,
        "notes": plan.notes,
        "is_published": plan.is_published,
        "publish_url": plan.publish_url,
        "published_at": plan.published_at,
        "play_note": plan.play_note,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def load_plan_data(db: Session, plan: ContentPlan) -> dict:
    owner_name = None
    if plan.owner_id is not None:
        owner_name = db.scalar(select(User.display_name).where(User.id == plan.owner_id))
    return plan_payload(plan, owner_name=owner_name)


def page_plans(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: ContentPlanStatus | None,
    plan_type: PlanType | None,
    channel_id: uuid.UUID | None,
    owner_id: uuid.UUID | None,
    is_published: bool | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    filters = [ContentPlan.project_id == project_id]
    if status is not None:
        filters.append(ContentPlan.status == status)
    if plan_type is not None:
        filters.append(ContentPlan.plan_type == plan_type)
    if channel_id is not None:
        filters.append(ContentPlan.channel_id == channel_id)
    if owner_id is not None:
        filters.append(ContentPlan.owner_id == owner_id)
    if is_published is not None:
        filters.append(ContentPlan.is_published.is_(is_published))

    total = db.scalar(select(func.count()).select_from(ContentPlan).where(*filters)) or 0
    rows = (
        db.execute(
            select(ContentPlan)
            .where(*filters)
            .order_by(
                ContentPlan.scheduled_at.asc().nullslast(),
                ContentPlan.created_at.desc(),
                ContentPlan.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    names = owner_names(db, {plan.owner_id for plan in rows if plan.owner_id is not None})
    return (
        [
            plan_payload(plan, owner_name=names.get(plan.owner_id) if plan.owner_id else None)
            for plan in rows
        ],
        total,
    )

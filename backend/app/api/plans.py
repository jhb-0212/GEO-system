"""运营计划：计划与排期，关联渠道、内容与公开站事实页。

计划本身不改内容正文，也不驱动发布；只维护排期、负责人和状态。
"""

import uuid

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, PlanCreated, PlanData, ok, ok_page
from app.core.errors import AppError, ResourceMissingError
from app.db.session import get_db
from app.models import (
    Channel,
    ContentItem,
    ContentPlan,
    ProjectMember,
    PublicPage,
    User,
)
from app.models.enums import ContentPlanStatus, PlanType
from app.schemas import PlanCreate, PlanUpdate
from app.services.audit import record_audit
from app.services.plan_publish_record import apply_publish_record, validate_publish_record

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/plans",
    tags=["运营计划"],
    responses=COMMON_ERRORS,
)


def _get_plan(db: Session, project_id: uuid.UUID, plan_id: uuid.UUID, *, for_update: bool = False) -> ContentPlan:
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


def _ensure_channel(db: Session, project_id: uuid.UUID, channel_id: uuid.UUID | None) -> None:
    if channel_id is None:
        return
    if db.scalar(select(Channel.id).where(Channel.project_id == project_id, Channel.id == channel_id)) is None:
        raise ResourceMissingError("渠道不存在", code="channel_missing")


def _ensure_content_item(db: Session, project_id: uuid.UUID, item_id: uuid.UUID | None) -> None:
    if item_id is None:
        return
    if db.scalar(select(ContentItem.id).where(ContentItem.project_id == project_id, ContentItem.id == item_id)) is None:
        raise ResourceMissingError("内容不存在", code="content_item_missing")


def _ensure_page(db: Session, project_id: uuid.UUID, page_id: uuid.UUID | None) -> None:
    if page_id is None:
        return
    if db.scalar(select(PublicPage.id).where(PublicPage.project_id == project_id, PublicPage.id == page_id)) is None:
        raise ResourceMissingError("公开站页面不存在", code="page_missing")


def _ensure_owner(db: Session, project_id: uuid.UUID, owner_id: uuid.UUID | None) -> None:
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
        raise ResourceMissingError("负责人不是当前项目的有效成员", code="owner_missing")


def _plan_data(db: Session, plan: ContentPlan) -> dict:
    owner_name = None
    if plan.owner_id is not None:
        owner_name = db.scalar(select(User.display_name).where(User.id == plan.owner_id))
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


@router.get("", response_model=PagedEnvelope[PlanData])
def list_plans(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    status: ContentPlanStatus | None = None,
    plan_type: PlanType | None = None,
    channel_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    is_published: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [ContentPlan.project_id == ctx.project.id]
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
    rows = db.execute(
        select(ContentPlan)
        .where(*filters)
        .order_by(ContentPlan.scheduled_at.asc().nullslast(), ContentPlan.created_at.desc(), ContentPlan.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return ok_page(
        [_plan_data(db, plan) for plan in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[PlanCreated])
def create_plan(
    payload: PlanCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_channel(db, ctx.project.id, payload.channel_id)
    _ensure_content_item(db, ctx.project.id, payload.content_item_id)
    _ensure_page(db, ctx.project.id, payload.site_page_id)
    _ensure_owner(db, ctx.project.id, payload.owner_id)
    publish_url = validate_publish_record(
        is_published=payload.is_published, publish_url=payload.publish_url
    )

    plan = ContentPlan(
        project_id=ctx.project.id,
        title=payload.title,
        plan_type=payload.plan_type,
        channel_id=payload.channel_id,
        content_item_id=payload.content_item_id,
        site_page_id=payload.site_page_id,
        owner_id=payload.owner_id or ctx.user.id,
        scheduled_at=payload.scheduled_at,
        status=payload.status,
        notes=payload.notes,
        is_published=payload.is_published,
        publish_url=publish_url,
        published_at=datetime.now(UTC) if payload.is_published else None,
        play_note=payload.play_note,
    )
    db.add(plan)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="plan.create",
        target_type="content_plan",
        target_id=plan.id,
        payload={
            "title": plan.title,
            "plan_type": plan.plan_type.value,
            "status": plan.status.value,
            "channel_id": str(plan.channel_id) if plan.channel_id else None,
            "content_item_id": str(plan.content_item_id) if plan.content_item_id else None,
            "site_page_id": str(plan.site_page_id) if plan.site_page_id else None,
        },
    )
    db.commit()
    return ok({"id": str(plan.id)})


@router.patch("/{plan_id}", response_model=Envelope[PlanData])
def update_plan(
    plan_id: uuid.UUID,
    payload: PlanUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    plan = _get_plan(db, ctx.project.id, plan_id, for_update=True)
    changes = payload.model_dump(exclude_unset=True)
    for field in ("title", "plan_type", "status"):
        if field in changes and changes[field] is None:
            raise AppError(f"{field} 不能为空", code="invalid_plan_update")

    if "channel_id" in changes:
        _ensure_channel(db, ctx.project.id, changes["channel_id"])
    if "content_item_id" in changes:
        _ensure_content_item(db, ctx.project.id, changes["content_item_id"])
    if "site_page_id" in changes:
        _ensure_page(db, ctx.project.id, changes["site_page_id"])
    if "owner_id" in changes:
        _ensure_owner(db, ctx.project.id, changes["owner_id"])

    # 发布记录三字段必须一起判定：只改其中任一字段时，用「合并后的现值」做互斥校验。
    # 撤回发布（is_published=False）本身就是要清链接，不再要求调用方同时传 publish_url=null。
    publish_keys = {"is_published", "publish_url", "play_note"}
    if publish_keys & changes.keys():
        target_published = changes.get("is_published", plan.is_published)
        if not target_published and changes.get("publish_url"):
            # 调用方想挂链接却没把计划置为已发布：直接报错，不静默丢弃
            validate_publish_record(is_published=False, publish_url=changes["publish_url"])
        target_url = None if not target_published else changes.get("publish_url", plan.publish_url)
        apply_publish_record(
            plan, is_published=target_published, publish_url=target_url
        )
    if "play_note" in changes:
        plan.play_note = changes["play_note"]

    audit_changes: dict[str, object] = {}
    for key, value in changes.items():
        if key in publish_keys:
            audit_changes[key] = getattr(plan, key, None)
            continue
        setattr(plan, key, value)
        if isinstance(value, uuid.UUID):
            audit_changes[key] = str(value)
        elif hasattr(value, "value"):
            audit_changes[key] = value.value
        elif hasattr(value, "isoformat"):
            audit_changes[key] = value.isoformat()
        else:
            audit_changes[key] = value
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="plan.update",
        target_type="content_plan",
        target_id=plan.id,
        payload={"changes": audit_changes},
    )
    db.commit()
    return ok(_plan_data(db, plan))

"""内容工厂模板：CRUD + 一键生成草稿。

生成只产出 draft 内容（ContentItem + ContentVersion），仍走审核；模板不是审核捷径。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.content import _content_hash
from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, ok_page, ok
from app.core.errors import AppError
from app.db.session import get_db
from app.models import ContentItem, ContentTemplate, ContentVersion
from app.models.enums import ContentKind, ContentStatus
from app.services.audit import record_audit
from app.services.content_templates import extract_slots, render

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/content-templates",
    tags=["内容模板"],
    responses=COMMON_ERRORS,
)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel_category: str | None = Field(default=None, max_length=32)
    question_type: str | None = Field(default=None, max_length=16)
    skeleton: str = Field(min_length=1, max_length=20000)
    notes: str | None = Field(default=None, max_length=2000)


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    channel_category: str | None = Field(default=None, max_length=32)
    question_type: str | None = Field(default=None, max_length=16)
    skeleton: str | None = Field(default=None, min_length=1, max_length=20000)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class GenerateIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    slot_values: dict[str, str] = Field(default_factory=dict)


def _serialize(row: ContentTemplate) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "channel_category": row.channel_category,
        "question_type": row.question_type,
        "skeleton": row.skeleton,
        "slots": row.slots,
        "notes": row.notes,
        "is_active": row.is_active,
        "created_at": row.created_at,
    }


def _require_template(db: Session, project_id: uuid.UUID, template_id: uuid.UUID) -> ContentTemplate:
    row = db.scalar(
        select(ContentTemplate).where(
            ContentTemplate.project_id == project_id,
            ContentTemplate.id == template_id,
        )
    )
    if row is None:
        raise AppError("模板不存在或不属于当前项目", code="template_not_found")
    return row


@router.get("", response_model=PagedEnvelope[dict])
def list_templates(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    include_inactive: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    filters = [ContentTemplate.project_id == ctx.project.id]
    if not include_inactive:
        filters.append(ContentTemplate.is_active.is_(True))
    total = int(db.scalar(select(func.count()).where(*filters)) or 0)
    rows = db.scalars(
        select(ContentTemplate).where(*filters)
        .order_by(ContentTemplate.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ok_page([_serialize(row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("", status_code=201, response_model=Envelope[dict])
def create_template(
    payload: TemplateIn,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
):
    slots = extract_slots(payload.skeleton)
    if not slots:
        raise AppError("骨架里至少要有一个 {{槽位}} 占位", code="template_no_slot")
    row = ContentTemplate(
        project_id=ctx.project.id,
        name=payload.name.strip(),
        channel_category=payload.channel_category,
        question_type=payload.question_type,
        skeleton=payload.skeleton,
        slots=slots,
        notes=payload.notes,
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.template_create",
        target_type="content_template",
        target_id=row.id,
        payload={"slots": [slot["key"] for slot in slots]},
    )
    db.commit()
    return ok(_serialize(row))


@router.patch("/{template_id}", response_model=Envelope[dict])
def update_template(
    template_id: uuid.UUID,
    payload: TemplateUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
):
    row = _require_template(db, ctx.project.id, template_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise AppError("没有需要更新的字段", code="empty_update")
    if "skeleton" in changes:
        slots = extract_slots(changes["skeleton"])
        if not slots:
            raise AppError("骨架里至少要有一个 {{槽位}} 占位", code="template_no_slot")
        row.slots = slots
    for key, value in changes.items():
        setattr(row, key, value)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.template_update",
        target_type="content_template",
        target_id=row.id,
        payload={"fields": sorted(changes)},
    )
    db.commit()
    return ok(_serialize(row))


@router.post("/{template_id}/generate", status_code=201, response_model=Envelope[dict])
def generate_from_template(
    template_id: uuid.UUID,
    payload: GenerateIn,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
):
    """按模板生成一篇草稿：正文由服务端渲染，前端不能自己拼。"""
    row = _require_template(db, ctx.project.id, template_id)
    if not row.is_active:
        raise AppError("模板已停用，不能生成", code="template_inactive")

    try:
        body = render(row.skeleton, payload.slot_values)
    except ValueError as exc:
        raise AppError(str(exc), code="template_slot_missing") from exc

    item = ContentItem(
        project_id=ctx.project.id,
        kind=ContentKind.MASTER,
        title=payload.title.strip(),
        status=ContentStatus.DRAFT,
        created_by=ctx.user.id,
    )
    db.add(item)
    db.flush()

    version = ContentVersion(
        project_id=ctx.project.id,
        item_id=item.id,
        version_no=1,
        body=body,
        content_hash=_content_hash(body),
        status=ContentStatus.DRAFT,
        change_note=f"由模板「{row.name}」生成",
        created_by=ctx.user.id,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.template_generate",
        target_type="content_item",
        target_id=item.id,
        payload={"template_id": str(row.id), "content_hash": version.content_hash},
    )
    db.commit()
    return ok(
        {
            "item_id": str(item.id),
            "version_id": str(version.id),
            "title": item.title,
            "body": body,
            "content_hash": version.content_hash,
            "status": version.status.value,
        }
    )

"""FAQ 管理接口：内部编辑走 content.read / content.write，公开只读另走 public 路由。"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_any_permission, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    FaqCreated,
    FaqData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import AppError, ConflictError, InsufficientPermissionError
from app.db.session import get_db
from app.models import Faq
from app.models.enums import FaqStatus
from app.schemas import FaqCreate, FaqUpdate
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/faqs",
    tags=["FAQ"],
    responses=COMMON_ERRORS,
)

# 公开口径：报名费用、具体开班日期、退款边界不对外发布。
# 这里做最后一道拦截，避免编辑误把敏感问答直接置为 published；内部 draft 不受影响。
PUBLIC_FAQ_SENSITIVE_TERMS = (
    "学费",
    "费用",
    "开班",
    "退款",
    "退费",
    "价格",
    "收费",
    "报名费",
)

# 允许编辑直接修改的正文范围；上架后必须走“下架 → 编辑 → 审核发布”闭环。
FAQ_CONTENT_FIELDS = frozenset({"question", "answer", "category"})


def _assert_public_scope(question: str, answer: str, status: FaqStatus) -> None:
    if status != FaqStatus.PUBLISHED:
        return
    hits = [term for term in PUBLIC_FAQ_SENSITIVE_TERMS if term in f"{question}\n{answer}"]
    if hits:
        raise AppError(
            "报名费用、具体开班日期、退款边界不对外公开；请保持 draft 或删除敏感表述",
            code="faq_public_scope_forbidden",
        )


def _serialize(row: Faq) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "question": row.question,
        "answer": row.answer,
        "category": row.category,
        "status": row.status,
        "sort_order": row.sort_order,
        "deleted_at": row.deleted_at,
        "deleted_by": str(row.deleted_by) if row.deleted_by else None,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("", response_model=PagedEnvelope[FaqData])
def list_faqs(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
    status: FaqStatus | None = Query(default=None, description="按状态筛选"),
    category: str | None = Query(default=None, max_length=64, description="按分类筛选"),
    deleted: bool | None = Query(default=None, description="true 只看已删除；不传只看未删除"),
    q: str | None = Query(default=None, max_length=200, description="在问题与答案中做包含搜索"),
) -> dict:
    base = select(Faq).where(Faq.project_id == ctx.project.id)
    if status is not None:
        base = base.where(Faq.status == status)
    if category:
        base = base.where(Faq.category == category)
    if deleted:
        base = base.where(Faq.deleted_at.is_not(None))
    else:
        base = base.where(Faq.deleted_at.is_(None))
    if q and q.strip():
        # % 和 _ 是 LIKE 通配符：不转义时搜「%」会匹配全部、「_」会匹配任意单字符。
        # 反斜杠先自我转义，再转义两个通配符，查询侧用 escape="\\" 还原为字面量。
        literal = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        keyword = f"%{literal}%"
        base = base.where(
            Faq.question.ilike(keyword, escape="\\") | Faq.answer.ilike(keyword, escape="\\")
        )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Faq.sort_order, Faq.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page([_serialize(row) for row in rows], page=page, page_size=page_size, total=total)


@router.get("/categories", response_model=Envelope[list[str]])
def list_faq_categories(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(
        select(Faq.category)
        .where(
            Faq.project_id == ctx.project.id,
            Faq.deleted_at.is_(None),
            Faq.category.is_not(None),
        )
        .distinct()
        .order_by(Faq.category)
    ).all()
    return ok([value for value in rows if value])


@router.post("", status_code=201, response_model=Envelope[FaqCreated])
def create_faq(
    payload: FaqCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    if payload.status == FaqStatus.PUBLISHED:
        raise InsufficientPermissionError(
            "FAQ 发布需独立审核；请先保存 draft，再由审核角色发布",
            code="faq_publish_requires_review",
        )
    _assert_public_scope(payload.question, payload.answer, payload.status)
    row = Faq(
        project_id=ctx.project.id,
        question=payload.question,
        answer=payload.answer,
        category=payload.category,
        status=payload.status,
        sort_order=payload.sort_order,
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="faq.create",
        target_type="faq",
        target_id=row.id,
        payload={"status": row.status, "question": row.question},
    )
    db.commit()
    return ok({"id": str(row.id)})


@router.patch("/{faq_id}", response_model=Envelope[FaqData])
def update_faq(
    faq_id: uuid.UUID,
    payload: FaqUpdate,
    ctx: ProjectContext = Depends(require_any_permission("content.write", "content.review")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Faq, ctx.project.id, resource="faq", id=faq_id)
    if row.deleted_at is not None:
        raise ConflictError("FAQ 已删除，请先恢复", code="faq_deleted")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise AppError("没有需要更新的字段", code="empty_update")

    old_status = row.status
    target_status = changes.get("status", row.status)
    content_changed = bool(FAQ_CONTENT_FIELDS & changes.keys())

    # 已上架正文必须先下架再改，避免编辑绕过审核直接替换公开答案。
    if old_status == FaqStatus.PUBLISHED and target_status == FaqStatus.PUBLISHED and content_changed:
        raise ConflictError(
            "已上架 FAQ 需先下架再修改正文",
            code="faq_published_content_locked",
        )
    # 从非公开状态改为 published 必须由 content.review 角色发起。
    if (
        target_status == FaqStatus.PUBLISHED
        and old_status != FaqStatus.PUBLISHED
        and "content.review" not in ctx.permissions
    ):
        raise InsufficientPermissionError(
            "FAQ 发布需独立审核；编辑只能保存 draft，由审核角色发布",
            code="faq_publish_requires_review",
        )
    # 审核角色没有 content.write：只能改状态，不能借 PATCH 改正文。
    if "content.write" not in ctx.permissions and content_changed:
        raise InsufficientPermissionError(
            "审核角色只能改变 FAQ 发布状态，不能修改正文",
            code="faq_content_write_forbidden",
        )

    _assert_public_scope(
        changes.get("question", row.question),
        changes.get("answer", row.answer),
        target_status,
    )
    for field, value in changes.items():
        setattr(row, field, value)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="faq.update",
        target_type="faq",
        target_id=row.id,
        payload={
            "fields": sorted(changes),
            "status_from": old_status,
            "status_to": target_status,
        },
    )
    db.commit()
    return ok(_serialize(row))


@router.delete("/{faq_id}", response_model=Envelope[FaqData])
def delete_faq(
    faq_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Faq, ctx.project.id, resource="faq", id=faq_id, for_update=True)
    if row.deleted_at is not None:
        raise ConflictError("FAQ 已删除", code="faq_already_deleted")
    was_published = row.status == FaqStatus.PUBLISHED
    row.status = FaqStatus.UNPUBLISHED
    row.deleted_at = datetime.now(timezone.utc)
    row.deleted_by = ctx.user.id
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="faq.delete",
        target_type="faq",
        target_id=row.id,
        payload={
            "soft_deleted": True,
            "was_published": was_published,
            "question": row.question,
            "deleted_at": row.deleted_at.isoformat(),
        },
    )
    db.commit()
    return ok(_serialize(row))


@router.post("/{faq_id}/restore", response_model=Envelope[FaqData])
def restore_faq(
    faq_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Faq, ctx.project.id, resource="faq", id=faq_id, for_update=True)
    if row.deleted_at is None:
        raise ConflictError("FAQ 未删除，不需要恢复", code="faq_not_deleted")
    row.deleted_at = None
    row.deleted_by = None
    row.status = FaqStatus.DRAFT
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="faq.restore",
        target_type="faq",
        target_id=row.id,
        payload={"question": row.question, "restored_status": row.status},
    )
    db.commit()
    return ok(_serialize(row))

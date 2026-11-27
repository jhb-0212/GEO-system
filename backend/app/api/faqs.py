"""FAQ 管理接口：内部编辑走 content.read / content.write，公开只读另走 public 路由。"""

import re
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
from app.schemas import FaqCreate, FaqReviewRequest, FaqUpdate
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row
from app.services.faq_listing import (
    faq_categories,
    page_faqs,
    page_review_queue,
)
from app.services.state_machine import ensure_faq_transition

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/faqs",
    tags=["FAQ"],
    responses=COMMON_ERRORS,
)

# 公开口径：不发布具体金额、具体开班日期、退款比例或保底数字。
# 2026-11-27 官网 /faq 已公开“学费包含什么/中途退出怎么处理”等口径后，这里从
# “按关键词一刀切”改为“拦截具体承诺”，避免把官网已经公开的说明误拦。
PUBLIC_FAQ_COMMITMENT_PATTERNS = (
    # 具体开班日期/时间，而非泛泛的上课安排
    re.compile(r"开班(?:日期|时间)|最近一期.{0,8}开班|下期.{0,8}开班"),
    # 金额：8000 元、1.2 万、8K 等
    re.compile(r"\d+(?:\.\d+)?\s*(?:元|万元|万|块|千|[kK])"),
    # 百分比/保底数字：50%、保 8K、起薪 8000
    re.compile(r"\d+\s*%|(?:保|保证|承诺|起薪)[^。；\n]{0,8}\d+(?:\.\d+)?\s*[kK千万元]?"),
    # 具体日期：2026 年 12 月、12 月 1 日
    re.compile(r"20\d{2}\s*年\s*\d{1,2}\s*月|\d{1,2}\s*月\s*\d{1,2}\s*日"),
)

# 允许编辑直接修改的正文范围；上架后必须走“下架 → 编辑 → 审核发布”闭环。
FAQ_CONTENT_FIELDS = frozenset({"question", "answer", "category"})


def _assert_public_scope(question: str, answer: str, status: FaqStatus) -> None:
    if status != FaqStatus.PUBLISHED:
        return
    text = f"{question}\n{answer}"
    if any(pattern.search(text) for pattern in PUBLIC_FAQ_COMMITMENT_PATTERNS):
        raise AppError(
            "公开 FAQ 不能包含具体金额、具体开班日期、退款比例或保底数字；"
            "请改成协议口径或保持 draft",
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
        "review_comment": row.review_comment,
        "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
        "reviewed_at": row.reviewed_at,
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
    total, rows = page_faqs(
        db,
        ctx.project.id,
        status=status,
        category=category,
        deleted=deleted,
        q=q,
        page=page,
        page_size=page_size,
    )
    return ok_page([_serialize(row) for row in rows], page=page, page_size=page_size, total=total)


@router.get("/categories", response_model=Envelope[list[str]])
def list_faq_categories(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    return ok(faq_categories(db, ctx.project.id))


@router.get("/review-queue", response_model=PagedEnvelope[FaqData])
def list_faq_review_queue(
    ctx: ProjectContext = Depends(require_permission("content.review")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
    category: str | None = Query(default=None, max_length=64, description="按分类筛选"),
    q: str | None = Query(default=None, max_length=200, description="在问题与答案中做包含搜索"),
) -> dict:
    """审核队列：只返回待审 FAQ，按提交/更新时间正序，先到先审。"""
    total, rows = page_review_queue(
        db,
        ctx.project.id,
        category=category,
        q=q,
        page=page,
        page_size=page_size,
    )
    return ok_page([_serialize(row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("", status_code=201, response_model=Envelope[FaqCreated])
def create_faq(
    payload: FaqCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    if payload.status != FaqStatus.DRAFT:
        if payload.status == FaqStatus.PUBLISHED:
            raise InsufficientPermissionError(
                "FAQ 发布需独立审核；请先保存 draft，提交审核后再发布",
                code="faq_publish_requires_review",
            )
        raise InsufficientPermissionError(
            "FAQ 新建只能保存 draft；请保存后走提交审核流程",
            code="faq_create_requires_draft",
        )
    row = Faq(
        project_id=ctx.project.id,
        question=payload.question,
        answer=payload.answer,
        category=payload.category,
        status=FaqStatus.DRAFT,
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
    row = require_scoped_row(db, Faq, ctx.project.id, resource="faq", id=faq_id, for_update=True)
    if row.deleted_at is not None:
        raise ConflictError("FAQ 已删除，请先恢复", code="faq_deleted")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise AppError("没有需要更新的字段", code="empty_update")

    content_changed = bool(FAQ_CONTENT_FIELDS & changes.keys())
    if "content.write" not in ctx.permissions:
        if content_changed:
            raise InsufficientPermissionError(
                "审核角色只能审核 FAQ，不能修改正文",
                code="faq_content_write_forbidden",
            )
        raise InsufficientPermissionError(
            "审核角色请使用审核队列的通过/驳回操作",
            code="faq_review_endpoint_required",
        )

    old_status = row.status
    target_status = changes.get("status", row.status)
    status_changed = "status" in changes
    if status_changed:
        if target_status == FaqStatus.PUBLISHED and "content.review" not in ctx.permissions:
            raise InsufficientPermissionError(
                "FAQ 发布需独立审核；请提交审核，由审核角色通过",
                code="faq_publish_requires_review",
            )
        if target_status not in {FaqStatus.DRAFT, FaqStatus.UNPUBLISHED}:
            raise AppError(
                "FAQ 待审、发布、驳回状态请使用提交审核或审核接口",
                code="faq_status_transition_requires_review_endpoint",
            )
        allowed_targets = {
            FaqStatus.DRAFT: {FaqStatus.DRAFT, FaqStatus.UNPUBLISHED},
            FaqStatus.UNPUBLISHED: {FaqStatus.UNPUBLISHED, FaqStatus.DRAFT},
            FaqStatus.PENDING_REVIEW: {FaqStatus.PENDING_REVIEW, FaqStatus.DRAFT},
            FaqStatus.REJECTED: {FaqStatus.REJECTED, FaqStatus.DRAFT},
            FaqStatus.PUBLISHED: {FaqStatus.PUBLISHED, FaqStatus.UNPUBLISHED},
        }
        if target_status not in allowed_targets[old_status]:
            raise ConflictError(
                "当前 FAQ 状态不允许该操作；已上架请先下架，待审请先撤回",
                code="faq_status_transition_not_allowed",
            )
    if content_changed and old_status == target_status:
        if old_status == FaqStatus.PUBLISHED:
            raise ConflictError(
                "已上架 FAQ 需先下架再修改正文",
                code="faq_published_content_locked",
            )
        if old_status == FaqStatus.PENDING_REVIEW:
            raise ConflictError(
                "待审核 FAQ 需先撤回再修改正文",
                code="faq_pending_review_locked",
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


@router.post("/{faq_id}/submit-review", response_model=Envelope[FaqData])
def submit_faq_review(
    faq_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    """编辑提交审核：draft/rejected/unpublished → pending_review。"""
    row = require_scoped_row(db, Faq, ctx.project.id, resource="faq", id=faq_id, for_update=True)
    if row.deleted_at is not None:
        raise ConflictError("FAQ 已删除，请先恢复", code="faq_deleted")
    if row.status == FaqStatus.PENDING_REVIEW:
        raise ConflictError("FAQ 已在审核队列中", code="faq_already_pending_review")
    if row.status == FaqStatus.PUBLISHED:
        raise ConflictError(
            "已上架 FAQ 需先下架，再重新提交审核",
            code="faq_published_needs_unpublish",
        )
    if row.status not in {FaqStatus.DRAFT, FaqStatus.REJECTED, FaqStatus.UNPUBLISHED}:
        raise ConflictError("当前 FAQ 状态不能提交审核", code="faq_status_transition_not_allowed")

    old_status = row.status
    row.status = ensure_faq_transition(row.status, FaqStatus.PENDING_REVIEW)
    # 重新提交视为新一轮审核：清掉上一轮意见，历史仍保留在审计日志里。
    row.review_comment = None
    row.reviewed_by = None
    row.reviewed_at = None
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="faq.submit_review",
        target_type="faq",
        target_id=row.id,
        payload={"status_from": old_status, "status_to": row.status, "question": row.question},
    )
    db.commit()
    return ok(_serialize(row))


@router.post("/{faq_id}/review", response_model=Envelope[FaqData])
def review_faq(
    faq_id: uuid.UUID,
    payload: FaqReviewRequest,
    ctx: ProjectContext = Depends(require_permission("content.review")),
    db: Session = Depends(get_db),
) -> dict:
    """审核通过/驳回：只有 pending_review 可审；驳回必须写意见。"""
    row = require_scoped_row(db, Faq, ctx.project.id, resource="faq", id=faq_id, for_update=True)
    if row.deleted_at is not None:
        raise ConflictError("FAQ 已删除，不能审核", code="faq_deleted")
    if row.status != FaqStatus.PENDING_REVIEW:
        raise ConflictError("FAQ 不在待审核状态", code="faq_not_pending_review")

    comment = payload.comment
    if payload.action == "reject" and not comment:
        raise AppError("驳回 FAQ 必须填写审核意见", code="faq_review_comment_required")
    target_status = FaqStatus.PUBLISHED if payload.action == "approve" else FaqStatus.REJECTED
    if target_status == FaqStatus.PUBLISHED:
        _assert_public_scope(row.question, row.answer, target_status)

    old_status = row.status
    row.status = ensure_faq_transition(row.status, target_status)
    row.review_comment = comment
    row.reviewed_by = ctx.user.id
    row.reviewed_at = datetime.now(timezone.utc)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="faq.review",
        target_type="faq",
        target_id=row.id,
        payload={
            "review_action": payload.action,
            "review_comment": comment,
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
    row.status = ensure_faq_transition(row.status, FaqStatus.UNPUBLISHED)
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
    row.status = ensure_faq_transition(row.status, FaqStatus.DRAFT)
    row.review_comment = None
    row.reviewed_by = None
    row.reviewed_at = None
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

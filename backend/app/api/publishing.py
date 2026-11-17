"""发布接口：读要 publish.read，建单 / 回执 / 核实 / 记录尝试要 publish.execute。

状态机（API 层强制）：只有 pending / needs_review 能新增 attempt；
unknown 必须先 verify（回 pending 重试或补回执结案），publishing 禁止重复提交，
published 是终态。建单 / 回执 / verify 三处均做审批 hash 守卫。
"""

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    PagedEnvelope,
    PublishAccountData,
    PublishAttemptCreated,
    PublishReceiptCreated,
    PublishTaskCreated,
    PublishTaskData,
    PublishVerifyResult,
    ok,
    ok_page,
)
from app.core.errors import ConflictError, ProjectAccessError, ReviewStateError
from app.db.session import get_db
from app.models import (
    Channel,
    ContentItem,
    ContentReview,
    ContentVersion,
    PublishAccount,
    PublishAttempt,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import (
    AttemptResult,
    ContentKind,
    ContentStatus,
    PublishTaskStatus,
    VerifyOutcome,
)
from app.schemas import (
    PublishAccountCreate,
    PublishAttemptCreate,
    PublishReceiptCreate,
    PublishTaskCreate,
    PublishVerifyRequest,
)
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row
from app.services.state_machine import ensure_content_transition, ensure_publish_transition
from app.services.trace_chain import trace_for_content_version

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/publish",
    tags=["发布"],
    responses=COMMON_ERRORS,
)


def _idempotency_key(
    account_id: uuid.UUID,
    channel_id: uuid.UUID,
    version_id: uuid.UUID,
    task_key: str,
) -> str:
    """四元组哈希：账号 + 渠道 + 内容版本 + 业务任务键；同四元组重复提交命中幂等，不重发。"""
    raw = f"{account_id}:{channel_id}:{version_id}:{task_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _guard_version_hash(
    db: Session,
    version: ContentVersion,
    *,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    """hash 守卫：比对最新审批快照与当前正文 hash；不一致退回 pending_review 并写审计，抛 409。

    覆盖建任务 / 回执 / verify 三个写入点；不做全表巡检。回落经 CONTENT_TRANSITIONS
    状态机校验（APPROVED / PUBLISHED 已补回 pending_review 出边），不走旁路。
    """
    latest_review = db.scalar(
        select(ContentReview)
        .where(ContentReview.version_id == version.id)
        .order_by(ContentReview.created_at.desc(), ContentReview.id.desc())
    )
    if latest_review is None:
        return
    if latest_review.content_hash_snapshot == version.content_hash:
        return
    version.status = ensure_content_transition(version.status, ContentStatus.PENDING_REVIEW)
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="content.hash_drift",
        target_type="content_version",
        target_id=version.id,
        payload={
            "snapshot_hash": latest_review.content_hash_snapshot,
            "current_hash": version.content_hash,
        },
    )
    db.commit()
    raise ReviewStateError("正文与审批快照不一致，已退回待审核")


@router.post(
    "/accounts",
    status_code=201,
    response_model=Envelope[PublishAccountData],
)
def create_account(
    payload: PublishAccountCreate,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """登记渠道发布账号；只存账号名与凭证引用，不接收真实密钥。"""
    channel = require_scoped_row(
        db, Channel, ctx.project.id, resource="channel", id=payload.channel_id
    )
    if not channel.is_active:
        raise ReviewStateError("渠道已停用，不能登记发布账号")

    existing = db.scalar(
        select(PublishAccount).where(
            PublishAccount.project_id == ctx.project.id,
            PublishAccount.channel_id == channel.id,
            PublishAccount.account_name == payload.account_name,
        )
    )
    if existing is not None:
        raise ConflictError("同一渠道下发布账号名称已存在", code="publish_account_exists")

    account = PublishAccount(
        project_id=ctx.project.id,
        channel_id=channel.id,
        account_name=payload.account_name,
        credential_ref=payload.credential_ref,
        notes=payload.notes,
        is_active=True,
    )
    db.add(account)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.account_create",
        target_type="publish_account",
        target_id=account.id,
        payload={"channel_id": str(channel.id), "account_name": account.account_name},
    )
    db.commit()
    return ok(
        {
            "id": str(account.id),
            "account_name": account.account_name,
            "channel_id": str(account.channel_id),
            "is_active": account.is_active,
            "notes": account.notes,
        }
    )


@router.get("/accounts", response_model=PagedEnvelope[PublishAccountData])
def list_accounts(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
    channel_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    filters = [PublishAccount.project_id == ctx.project.id]
    if channel_id is not None:
        filters.append(PublishAccount.channel_id == channel_id)

    total = db.scalar(select(func.count()).select_from(PublishAccount).where(*filters)) or 0
    rows = db.scalars(
        select(PublishAccount)
        .where(*filters)
        .order_by(PublishAccount.account_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(row.id),
                "account_name": row.account_name,
                "channel_id": str(row.channel_id),
                "is_active": row.is_active,
                "notes": row.notes,
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/tasks", response_model=PagedEnvelope[PublishTaskData])
def list_tasks(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
    status: PublishTaskStatus | None = None,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    filters = [PublishTask.project_id == ctx.project.id]
    if status is not None:
        filters.append(PublishTask.status == status)

    total = db.scalar(select(func.count()).select_from(PublishTask).where(*filters)) or 0
    rows = db.scalars(
        select(PublishTask)
        .where(*filters)
        .order_by(PublishTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(row.id),
                "status": row.status,
                "channel_id": str(row.channel_id),
                "version_id": str(row.version_id),
                "trace_id": row.trace_id,
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/tasks/{task_id}/attempts",
    status_code=201,
    response_model=Envelope[PublishAttemptCreated],
)
def create_attempt(
    task_id: uuid.UUID,
    payload: PublishAttemptCreate,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    task = require_scoped_row(
        db,
        PublishTask,
        ctx.project.id,
        resource="publish_task",
        for_update=True,
        id=task_id,
    )

    target_status = (
        PublishTaskStatus.PUBLISHING
        if payload.result == AttemptResult.SUCCESS
        else PublishTaskStatus.FAILED
    )
    ensure_publish_transition(task.status, target_status)

    previous_max = db.scalar(
        select(func.max(PublishAttempt.attempt_no)).where(PublishAttempt.task_id == task.id)
    )
    attempt_no = (previous_max or 0) + 1
    now = datetime.now(timezone.utc)
    attempt = PublishAttempt(
        project_id=ctx.project.id,
        task_id=task.id,
        attempt_no=attempt_no,
        mode=payload.mode,
        result=payload.result,
        started_at=now,
        finished_at=now,
        error_code=payload.error_code,
        error_note=payload.error_note,
        operator_id=ctx.user.id,
    )
    db.add(attempt)
    task.status = target_status
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.attempt",
        target_type="publish_task",
        target_id=task.id,
        payload={"attempt_no": attempt_no, "result": payload.result.value, "task_status": task.status.value},
    )
    db.commit()
    return ok({"attempt_id": str(attempt.id), "attempt_no": attempt_no, "task_status": task.status})


@router.post("/tasks", status_code=201, response_model=Envelope[PublishTaskCreated])
def create_publish_task(
    payload: PublishTaskCreate,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", id=payload.version_id
    )
    if version.status != ContentStatus.APPROVED:
        raise ReviewStateError("只有审批通过的版本可以建发布任务")
    item = require_scoped_row(
        db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id
    )
    if item.kind != ContentKind.CHANNEL:
        raise ReviewStateError("只有渠道稿可以建发布任务")

    channel = require_scoped_row(
        db, Channel, ctx.project.id, resource="channel", id=payload.channel_id
    )
    if not channel.is_active:
        raise ReviewStateError("渠道已停用，不能建发布任务")

    account = require_scoped_row(
        db, PublishAccount, ctx.project.id, resource="publish_account", id=payload.account_id
    )
    if account.channel_id != channel.id:
        raise ProjectAccessError("账号不属于该渠道")
    if not account.is_active:
        raise ReviewStateError("发布账号已停用")

    _guard_version_hash(db, version, project_id=ctx.project.id, actor_id=ctx.user.id)

    # 发布侧 trace 从内容版本引用的监测证据继承；多条 trace 时不猜，留空。
    trace_id = trace_for_content_version(db, version.id)

    task_key = payload.task_key
    idempotency_key = _idempotency_key(account.id, channel.id, version.id, task_key)
    existing = db.scalar(
        select(PublishTask).where(
            PublishTask.project_id == ctx.project.id,
            PublishTask.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return ok(
            {
                "task_id": str(existing.id),
                "status": existing.status.value,
                "idempotency_key": idempotency_key,
                "reused": True,
                "trace_id": existing.trace_id,
            }
        )

    task = PublishTask(
        project_id=ctx.project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=task_key,
        idempotency_key=idempotency_key,
        publish_mode=payload.publish_mode,
        status=PublishTaskStatus.PENDING,
        trace_id=trace_id,
        scheduled_at=payload.scheduled_at,
        created_by=ctx.user.id,
    )
    try:
        db.add(task)
        db.flush()
    except IntegrityError as exc:
        # 并发同四元组同时建单：唯一约束只放行一个，另一个回滚后复用已提交的任务，
        # 不能把竞态暴露成 500，也不能重复写审计。
        db.rollback()
        existing = db.scalar(
            select(PublishTask).where(
                PublishTask.project_id == ctx.project.id,
                PublishTask.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise ConflictError("发布任务创建冲突，请重试", code="publish_task_conflict") from exc
        return ok(
            {
                "task_id": str(existing.id),
                "status": existing.status.value,
                "idempotency_key": idempotency_key,
                "reused": True,
                "trace_id": existing.trace_id,
            }
        )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.task_create",
        target_type="publish_task",
        target_id=task.id,
        payload={
            "version_id": str(version.id),
            "channel_id": str(channel.id),
            "account_id": str(account.id),
            "task_key": task_key,
            "trace_id": trace_id,
        },
    )
    db.commit()
    return ok(
        {
            "task_id": str(task.id),
            "status": task.status.value,
            "idempotency_key": idempotency_key,
            "reused": False,
            "trace_id": trace_id,
        }
    )


@router.post(
    "/tasks/{task_id}/receipts",
    response_model=Envelope[PublishReceiptCreated],
)
def create_receipt(
    task_id: uuid.UUID,
    payload: PublishReceiptCreate,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    task = require_scoped_row(
        db,
        PublishTask,
        ctx.project.id,
        resource="publish_task",
        for_update=True,
        id=task_id,
    )
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", id=task.version_id
    )
    _guard_version_hash(db, version, project_id=ctx.project.id, actor_id=ctx.user.id)

    if task.status != PublishTaskStatus.PUBLISHING:
        raise ReviewStateError("仅发布中的任务可回填回执结案；回执不明(unknown)须先经 verify")
    target = ensure_publish_transition(task.status, PublishTaskStatus.PUBLISHED)

    now = datetime.now(timezone.utc)
    receipt = PublishReceipt(
        project_id=ctx.project.id,
        task_id=task.id,
        attempt_id=payload.attempt_id,
        published_url=payload.published_url,
        receipt_payload=payload.receipt_payload,
        received_at=now,
        verified_by=ctx.user.id,
        verified_at=now,
    )
    db.add(receipt)
    task.status = target
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.receipt",
        target_type="publish_task",
        target_id=task.id,
        payload={"receipt_id": str(receipt.id), "published_url": payload.published_url},
    )
    db.commit()
    return ok(
        {"receipt_id": str(receipt.id), "task_id": str(task.id), "status": target.value}
    )


@router.post(
    "/tasks/{task_id}/verify",
    response_model=Envelope[PublishVerifyResult],
)
def verify_task(
    task_id: uuid.UUID,
    payload: PublishVerifyRequest,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    task = require_scoped_row(
        db,
        PublishTask,
        ctx.project.id,
        resource="publish_task",
        for_update=True,
        id=task_id,
    )
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", id=task.version_id
    )
    _guard_version_hash(db, version, project_id=ctx.project.id, actor_id=ctx.user.id)

    if task.status != PublishTaskStatus.UNKNOWN:
        raise ReviewStateError("只有回执不明(unknown)的任务可以核实")

    now = datetime.now(timezone.utc)
    if payload.outcome == VerifyOutcome.PUBLISHED:
        target = ensure_publish_transition(task.status, PublishTaskStatus.PUBLISHED)
        if payload.published_url:
            receipt = PublishReceipt(
                project_id=ctx.project.id,
                task_id=task.id,
                published_url=payload.published_url,
                receipt_payload=payload.receipt_payload,
                received_at=now,
                verified_by=ctx.user.id,
                verified_at=now,
            )
            db.add(receipt)
    else:
        target = ensure_publish_transition(task.status, PublishTaskStatus.PENDING)

    task.status = target
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.verify",
        target_type="publish_task",
        target_id=task.id,
        payload={"outcome": payload.outcome.value, "task_status": target.value},
    )
    db.commit()
    return ok({"task_id": str(task.id), "status": target.value})

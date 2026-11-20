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

from app.api.deps import ProjectContext, require_any_permission, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    PagedEnvelope,
    PublishAccountData,
    PublishAttemptCreated,
    PublishExecuteData,
    PublishReceiptCreated,
    PublishTaskCancelled,
    PublishTaskCreated,
    PublishTaskData,
    PublishVerifyResult,
    ok,
    ok_page,
)
from app.core.config import settings
from app.core.credentials import read_credential_env
from app.core.errors import (
    AppError,
    ConflictError,
    ProjectAccessError,
    ReviewStateError,
    ServiceUnavailableError,
)
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
    ChannelStatus,
    ContentKind,
    ContentStatus,
    PublishMode,
    PublishTaskStatus,
    VerifyOutcome,
)
from app.schemas import (
    PublishAccountCreate,
    PublishAccountUpdate,
    PublishAttemptCreate,
    PublishReceiptCreate,
    PublishTaskCreate,
    PublishVerifyRequest,
    PublishWeChatExecuteRequest,
)
from app.services.audit import record_audit
from app.services.channel_access import ensure_channel_approved
from app.services.citation_attribution import backfill_channel_for_url
from app.services.content_status import mark_version_status
from app.services.project_scope import require_scoped_row
from app.services.state_machine import ensure_content_transition, ensure_publish_transition
from app.services.trace_chain import trace_for_content_version
from app.services.wechat_publisher import (
    WeChatOfficialPublisher,
    WeChatPublisherError,
    build_wechat_digest,
    render_wechat_html,
)

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


def _promote_channel_on_publish(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel_id: uuid.UUID,
) -> None:
    """发布结案（回执或 verify 确认 published）后，把渠道台账推进到「已发布」。

    渠道状态语义：candidate（候选，未发过）/ review_pending（待归类）→ published（
    已在该渠道发布过内容）；observed 是已经观测到的更高状态，published 不回退。
    发布任务是渠道产出的唯一真实信号，因此联动发生在这里，而不是渠道手工改状态。
    """
    channel = db.scalar(
        select(Channel).where(
            Channel.project_id == project_id,
            Channel.id == channel_id,
        )
    )
    if channel is None:
        return
    if channel.status in {ChannelStatus.CANDIDATE, ChannelStatus.REVIEW_PENDING}:
        channel.status = ChannelStatus.PUBLISHED


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
    item = db.get(ContentItem, version.item_id)
    if item is not None and item.current_version_id == version.id:
        item.status = version.status
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
    ensure_channel_approved(channel)

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
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "同一渠道下发布账号名称已存在", code="publish_account_exists"
        ) from exc
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


@router.patch("/accounts/{account_id}", response_model=Envelope[PublishAccountData])
def update_account(
    account_id: uuid.UUID,
    payload: PublishAccountUpdate,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """账号换绑：渠道不变，只改账号名、凭证引用、备注和启停。

    原地更新而不是新建账号，保证已挂在该账号下的 pending 任务继续有效。
    """
    account = require_scoped_row(
        db,
        PublishAccount,
        ctx.project.id,
        resource="publish_account",
        for_update=True,
        id=account_id,
    )
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise AppError("没有可更新的字段", code="publish_account_no_changes")

    if "account_name" in updates:
        if updates["account_name"] is None:
            raise AppError("账号名称不能为空", code="invalid_account_name")
        name = updates["account_name"]
        existing = db.scalar(
            select(PublishAccount).where(
                PublishAccount.project_id == ctx.project.id,
                PublishAccount.channel_id == account.channel_id,
                PublishAccount.account_name == name,
                PublishAccount.id != account.id,
            )
        )
        if existing is not None:
            raise ConflictError("同一渠道下发布账号名称已存在", code="publish_account_exists")
        account.account_name = name

    if "credential_ref" in updates:
        account.credential_ref = updates["credential_ref"]
    if "notes" in updates:
        notes = updates["notes"]
        account.notes = notes.strip() if notes and notes.strip() else None
    if "is_active" in updates:
        account.is_active = updates["is_active"]

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "同一渠道下发布账号名称已存在", code="publish_account_exists"
        ) from exc
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.account_update",
        target_type="publish_account",
        target_id=account.id,
        payload={
            "channel_id": str(account.channel_id),
            "account_name": account.account_name,
            "changes": sorted(updates.keys()),
            "is_active": account.is_active,
        },
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
    rows = db.execute(
        select(
            PublishTask,
            ContentVersion.version_no,
            ContentItem.title,
            PublishAccount.id,
            PublishAccount.account_name,
        )
        .join(ContentVersion, ContentVersion.id == PublishTask.version_id)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .outerjoin(PublishAccount, PublishAccount.id == PublishTask.account_id)
        .where(*filters)
        .order_by(PublishTask.created_at.desc(), PublishTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(row.id),
                "serial_no": row.serial_no,
                "status": row.status,
                "channel_id": str(row.channel_id),
                "account_id": str(account_id) if account_id else None,
                "account_name": account_name,
                "version_id": str(row.version_id),
                "version_no": version_no,
                "version_title": version_title,
                "trace_id": row.trace_id,
            }
            for row, version_no, version_title, account_id, account_name in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=Envelope[PublishTaskCancelled],
)
def cancel_task(
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_any_permission("publish.cancel", "publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """取消尚未进入发布流程的任务：保留任务与回执记录，不做物理删除。

    publishing / published / unknown 不在此处取消：publishing 可能已经发出，
    published 是终态，unknown 需要先核实结果。取消只影响队列，不回滚内容版本，
    稿子仍可重新建一条发布任务。
    """
    task = require_scoped_row(
        db,
        PublishTask,
        ctx.project.id,
        resource="publish_task",
        for_update=True,
        id=task_id,
    )
    if task.status not in (PublishTaskStatus.PENDING, PublishTaskStatus.NEEDS_REVIEW):
        raise ReviewStateError("只有待发布或需复核的任务可以取消；已发出或已发布的任务不能取消")
    ensure_publish_transition(task.status, PublishTaskStatus.CANCELLED)

    previous_status = task.status
    task.status = PublishTaskStatus.CANCELLED
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.task_cancel",
        target_type="publish_task",
        target_id=task.id,
        payload={
            "serial_no": task.serial_no,
            "from": previous_status.value,
            "to": PublishTaskStatus.CANCELLED.value,
            "channel_id": str(task.channel_id),
            "account_id": str(task.account_id) if task.account_id else None,
            "version_id": str(task.version_id),
        },
    )
    db.commit()
    return ok({"task_id": str(task.id), "status": PublishTaskStatus.CANCELLED.value})


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
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", id=task.version_id
    )

    if payload.result == AttemptResult.SUCCESS:
        target_status = PublishTaskStatus.PUBLISHING
    elif payload.result == AttemptResult.UNKNOWN:
        target_status = PublishTaskStatus.UNKNOWN
    else:
        target_status = PublishTaskStatus.FAILED
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
    # 发布尝试成功先进入“已排期/发布中”，失败则要人工关注；回执结案才进入 published。
    mark_version_status(
        db,
        version,
        ContentStatus.PENDING_PUBLISH
        if payload.result == AttemptResult.SUCCESS
        else ContentStatus.NEEDS_ATTENTION,
    )
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.attempt",
        target_type="publish_task",
        target_id=task.id,
        payload={
            "attempt_no": attempt_no,
            "result": payload.result.value,
            "task_status": task.status.value,
            "content_status": version.status.value,
        },
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
    item = require_scoped_row(
        db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id
    )
    if item.kind != ContentKind.CHANNEL:
        raise ReviewStateError("只有渠道稿可以建发布任务")
    # 只允许发布当前版本：母稿 v1/v2 同时 approved 时，旧版本不能被重新发出去。
    if item.current_version_id != version.id:
        raise ReviewStateError("只能发布当前内容版本，请先确认版本未被新版本替代")

    channel = require_scoped_row(
        db, Channel, ctx.project.id, resource="channel", id=payload.channel_id
    )
    if not channel.is_active:
        raise ReviewStateError("渠道已停用，不能建发布任务")
    ensure_channel_approved(channel)

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
                "serial_no": existing.serial_no,
                "status": existing.status.value,
                "idempotency_key": idempotency_key,
                "reused": True,
                "trace_id": existing.trace_id,
            }
        )

    # 首次建单要求审批通过；已排期版本允许为新的渠道/任务键再建单。
    if version.status not in (ContentStatus.APPROVED, ContentStatus.PENDING_PUBLISH):
        raise ReviewStateError("只有审批通过或待发布的版本可以建发布任务")

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
                "serial_no": existing.serial_no,
                "status": existing.status.value,
                "idempotency_key": idempotency_key,
                "reused": True,
                "trace_id": existing.trace_id,
            }
        )
    # 建单即视为已排期；真正 published 必须等到回执或核实。
    mark_version_status(db, version, ContentStatus.PENDING_PUBLISH)
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
            "content_status": version.status.value,
        },
    )
    db.commit()
    return ok(
        {
            "task_id": str(task.id),
            "serial_no": task.serial_no,
            "status": task.status.value,
            "idempotency_key": idempotency_key,
            "reused": False,
            "trace_id": trace_id,
        }
    )


@router.post(
    "/tasks/{task_id}/execute",
    response_model=Envelope[PublishExecuteData],
)
def execute_publish_task(
    task_id: uuid.UUID,
    payload: PublishWeChatExecuteRequest,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """执行微信公众号官方 API 任务：草稿 → 发布 → 能拿到 URL 就自动结案。

    只有 `publish_mode=api`、渠道 code 命中 `WECHAT_MP_CHANNEL_CODE` 的任务可走这里；
    人工任务仍走回执。微信明确拒绝落 failed；超时/5xx 落 unknown，不自动重试。
    """
    task = require_scoped_row(
        db,
        PublishTask,
        ctx.project.id,
        resource="publish_task",
        for_update=True,
        id=task_id,
    )
    if task.publish_mode != PublishMode.API:
        raise ReviewStateError("只有官方 API 模式任务可以执行；人工任务请回填回执")
    if task.status not in (PublishTaskStatus.PENDING, PublishTaskStatus.NEEDS_REVIEW):
        raise ReviewStateError("只有待发布/待复核任务可以执行官方 API")

    channel = require_scoped_row(
        db, Channel, ctx.project.id, resource="channel", id=task.channel_id
    )
    if channel.code.strip() != settings.wechat_mp_channel_code.strip():
        raise ReviewStateError(
            f"当前只接入微信公众号官方 API，渠道 {channel.code} 尚未支持"
        )

    account = require_scoped_row(
        db, PublishAccount, ctx.project.id, resource="publish_account", id=task.account_id
    )
    if not account.is_active:
        raise ReviewStateError("发布账号已停用")

    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", id=task.version_id
    )
    item = require_scoped_row(
        db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id
    )
    if item.kind != ContentKind.CHANNEL:
        raise ReviewStateError("只有渠道稿可以执行发布")
    if item.current_version_id != version.id:
        raise ReviewStateError("只能发布当前内容版本")
    _guard_version_hash(db, version, project_id=ctx.project.id, actor_id=ctx.user.id)
    if version.status not in (ContentStatus.APPROVED, ContentStatus.PENDING_PUBLISH):
        raise ReviewStateError("只有审批通过或待发布的版本可以执行发布")

    app_id = settings.wechat_mp_app_id.strip()
    secret_ref = (account.credential_ref or "").strip() or "WECHAT_MP_SECRET_KEY"
    app_secret = read_credential_env(secret_ref)
    if not app_id or not app_secret:
        raise ServiceUnavailableError(
            "微信公众号官方 API 未配置：需要 WECHAT_MP_APP_ID，且账号 credential_ref 指向的 Secret 已配置",
            code="wechat_mp_not_configured",
        )

    try:
        content_html = render_wechat_html(version.body)
    except WeChatPublisherError as exc:
        raise ReviewStateError(str(exc), code=exc.code) from exc
    digest = (payload.digest or "").strip() or build_wechat_digest(version.body)
    author = (payload.author or settings.wechat_mp_author or "").strip()
    thumb_media_id = (
        payload.thumb_media_id or settings.wechat_mp_default_thumb_media_id or ""
    ).strip()

    target = ensure_publish_transition(task.status, PublishTaskStatus.PUBLISHING)
    task.status = target
    now = datetime.now(timezone.utc)
    previous_max = db.scalar(
        select(func.max(PublishAttempt.attempt_no)).where(PublishAttempt.task_id == task.id)
    )
    attempt_no = (previous_max or 0) + 1
    attempt = PublishAttempt(
        project_id=ctx.project.id,
        task_id=task.id,
        attempt_no=attempt_no,
        mode=PublishMode.API,
        result=AttemptResult.UNKNOWN,
        started_at=now,
        operator_id=ctx.user.id,
    )
    db.add(attempt)
    db.flush()
    # 先落“发布中”再发外部请求：进程在微信调用中途崩溃时，任务不会退回 pending 被重复发送。
    db.commit()

    result = None
    error: WeChatPublisherError | None = None
    try:
        with WeChatOfficialPublisher(
            app_id,
            app_secret,
            base_url=settings.wechat_mp_api_base_url,
            timeout=settings.wechat_mp_timeout_seconds,
        ) as publisher:
            result = publisher.publish_article(
                title=item.title,
                content_html=content_html,
                author=author,
                digest=digest,
                content_source_url=payload.content_source_url or "",
                thumb_media_id=thumb_media_id,
            )
    except WeChatPublisherError as exc:
        error = exc

    attempt.finished_at = datetime.now(timezone.utc)
    receipt: PublishReceipt | None = None
    if error is not None:
        attempt.error_code = error.code
        attempt.error_note = str(error)[:2000]
        if error.ambiguous:
            attempt.result = AttemptResult.UNKNOWN
            task.status = PublishTaskStatus.UNKNOWN
        else:
            attempt.result = AttemptResult.FAILED
            task.status = PublishTaskStatus.FAILED
        mark_version_status(db, version, ContentStatus.NEEDS_ATTENTION)
    else:
        assert result is not None
        attempt.result = AttemptResult.SUCCESS
        task.external_task_id = (result.publish_id or result.media_id)[:128]
        if result.article_url:
            task.status = ensure_publish_transition(
                task.status, PublishTaskStatus.PUBLISHED
            )
            receipt = PublishReceipt(
                project_id=ctx.project.id,
                task_id=task.id,
                attempt_id=attempt.id,
                published_url=result.article_url,
                receipt_payload={
                    "platform": "wechat_mp",
                    "media_id": result.media_id,
                    "publish_id": result.publish_id,
                    "status_note": result.status_note,
                },
                received_at=datetime.now(timezone.utc),
                verified_by=ctx.user.id,
                verified_at=datetime.now(timezone.utc),
            )
            db.add(receipt)
            mark_version_status(db, version, ContentStatus.PUBLISHED)
            _promote_channel_on_publish(
                db, project_id=ctx.project.id, channel_id=task.channel_id
            )
            db.flush()
            backfill_channel_for_url(db, ctx.project.id, result.article_url, task.channel_id)
        else:
            # 已提交但还没拿到文章 URL：保持 publishing，运营拿到 URL 后补回执结案。
            task.status = PublishTaskStatus.PUBLISHING
            mark_version_status(db, version, ContentStatus.PENDING_PUBLISH)

    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.wechat_execute",
        target_type="publish_task",
        target_id=task.id,
        payload={
            "attempt_no": attempt_no,
            "task_status": task.status.value,
            "media_id": result.media_id if result else None,
            "publish_id": result.publish_id if result else None,
            "article_url": result.article_url if result else None,
            "error_code": error.code if error else None,
            "ambiguous": bool(error.ambiguous) if error else False,
            "content_status": version.status.value,
        },
    )
    db.commit()
    return ok(
        {
            "task_id": str(task.id),
            "status": task.status.value,
            "attempt_id": str(attempt.id),
            "attempt_no": attempt_no,
            "media_id": result.media_id if result else None,
            "publish_id": result.publish_id if result else None,
            "article_url": result.article_url if result else None,
            "receipt_id": str(receipt.id) if receipt else None,
            "error_code": error.code if error else None,
            "error_note": str(error) if error else None,
            "status_note": result.status_note if result else None,
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

    if payload.attempt_id is not None:
        attempt = require_scoped_row(
            db,
            PublishAttempt,
            ctx.project.id,
            resource="publish_attempt",
            id=payload.attempt_id,
        )
        if attempt.task_id != task.id:
            raise ReviewStateError("回执引用的发布尝试不属于当前任务")
        if attempt.result != AttemptResult.SUCCESS:
            raise ReviewStateError("只有成功的发布尝试可以回填回执")

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
    # 回执是内容“已发布”的唯一结案信号；同步版本与当前条目状态，并推进渠道台账。
    mark_version_status(db, version, ContentStatus.PUBLISHED)
    _promote_channel_on_publish(db, project_id=ctx.project.id, channel_id=task.channel_id)
    db.flush()
    backfill_channel_for_url(db, ctx.project.id, payload.published_url, task.channel_id)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.receipt",
        target_type="publish_task",
        target_id=task.id,
        payload={
            "receipt_id": str(receipt.id),
            "published_url": payload.published_url,
            "content_status": version.status.value,
        },
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
        content_target = ContentStatus.PUBLISHED
    else:
        target = ensure_publish_transition(task.status, PublishTaskStatus.PENDING)
        content_target = ContentStatus.NEEDS_ATTENTION

    task.status = target
    mark_version_status(db, version, content_target)
    if target == PublishTaskStatus.PUBLISHED:
        _promote_channel_on_publish(db, project_id=ctx.project.id, channel_id=task.channel_id)
    db.flush()
    if target == PublishTaskStatus.PUBLISHED and payload.published_url:
        backfill_channel_for_url(db, ctx.project.id, payload.published_url, task.channel_id)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.verify",
        target_type="publish_task",
        target_id=task.id,
        payload={
            "outcome": payload.outcome.value,
            "task_status": target.value,
            "content_status": version.status.value,
        },
    )
    db.commit()
    return ok({"task_id": str(task.id), "status": target.value})

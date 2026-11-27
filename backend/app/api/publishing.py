"""发布接口：读要 publish.read，建单 / 回执 / 核实 / 记录尝试要 publish.execute。

状态机（API 层强制）：只有 pending / needs_review 能新增 attempt；
unknown 必须先 verify（回 pending 重试或补回执结案），publishing 禁止重复提交，
published 是终态。建单 / 回执 / verify 三处均做审批 hash 守卫。

列表口径（任务页、回执页的 join 与「转人工原因」取最新一条）在
`services/publish_listing.py`，本文件只留鉴权、状态守卫与写库。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_any_permission, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    PagedEnvelope,
    PublishAccountData,
    PublishAccountDeleted,
    PublishAttemptCreated,
    PublishExecuteData,
    PublishHandoffData,
    PublishReceiptCreated,
    PublishReceiptData,
    PublishTaskCancelled,
    PublishTaskCreated,
    PublishTaskData,
    PublishVerifyResult,
    ok,
    ok_page,
)
from app.core.config import settings
from app.core.errors import (
    AppError,
    ConflictError,
    ProjectAccessError,
    ReviewStateError,
)
from app.db.session import get_db
from app.models import (
    BudgetApproval,
    Channel,
    ContentItem,
    ContentVersion,
    OAuthConnection,
    PublishAccount,
    PublishAttempt,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import (
    AttemptResult,
    ChannelStatus,
    ContentKind,
    ContentFormat,
    ContentStatus,
    OAuthConnectionStatus,
    PublishHandoffReason,
    PublishMode,
    PublishTaskStatus,
    VerifyOutcome,
)
from app.schemas import (
    PublishAccountCreate,
    PublishAccountUpdate,
    PublishAttemptCreate,
    PublishHandoffCreate,
    PublishReceiptCreate,
    PublishTaskCreate,
    PublishVerifyRequest,
    PublishWeChatExecuteRequest,
)
from app.services.audit import record_audit
from app.services.budget_receipts import link_receipt_to_budget
from app.services.channel_access import ensure_channel_approved
from app.services.citation_attribution import backfill_channel_for_url
from app.services.content_status import mark_version_status, sync_current_item_status
from app.services.page_approval_service import require_publishable_page_approval
from app.services.project_scope import require_scoped_row
from app.services.publish_listing import (
    account_bound_to_oauth,
    account_name_exists,
    account_task_count,
    channel_name as channel_display_name,
    channel_row as channel_by_id,
    latest_content_review,
    latest_handoff_attempt,
    next_attempt_no,
    task_by_idempotency,
    HANDOFF_ERROR_CODES,
    account_payload as _account_payload,
    page_accounts,
    page_receipts,
    page_tasks,
)
from app.services.state_machine import (
    ensure_channel_transition,
    ensure_content_transition,
)
from app.services.todo_clock import apply_publish_status
from app.services.trace_chain import trace_for_content_version
from app.services.publish_execution import (
    PublishDelivery,
    execute_wechat_publish,
    guard_version_hash as _guard_version_hash,
    promote_channel_on_publish as _promote_channel_on_publish,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/publish",
    tags=["发布"],
    responses=COMMON_ERRORS,
)


# 幂等键算法与批次投喂共用一份（services.publish_task_keys），避免两条入口算出两种 key。
from app.services.publish_task_keys import idempotency_key as _idempotency_key


def _resolve_oauth_binding(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel_id: uuid.UUID,
    connection_id: uuid.UUID | None,
) -> OAuthConnection | None:
    """校验发布账号绑定的 OAuth 连接；令牌只留在 oauth_connections 密文列。"""
    if connection_id is None:
        return None
    connection = require_scoped_row(
        db,
        OAuthConnection,
        project_id,
        resource="oauth_connection",
        id=connection_id,
    )
    if connection.status != OAuthConnectionStatus.CONNECTED:
        raise ConflictError(
            "该 OAuth 连接不是已连接状态，不能绑定到发布账号",
            code="oauth_connection_not_usable",
        )
    if not connection.access_token_encrypted:
        raise ConflictError(
            "该 OAuth 连接没有服务端令牌，不能绑定到发布账号",
            code="oauth_token_missing",
        )
    if connection.channel_id is not None and connection.channel_id != channel_id:
        raise ConflictError(
            "OAuth 连接绑定渠道与发布账号渠道不一致",
            code="oauth_channel_mismatch",
        )
    return connection


def _ensure_oauth_not_bound_to_other_account(
    db: Session,
    *,
    project_id: uuid.UUID,
    connection_id: uuid.UUID | None,
    account_id: uuid.UUID | None = None,
) -> None:
    if connection_id is None:
        return
    if account_bound_to_oauth(
        db, project_id, connection_id, exclude_account_id=account_id
    ):
        raise ConflictError(
            "该 OAuth 连接已绑定其他发布账号，请先解绑",
            code="publish_account_oauth_in_use",
        )


def _oauth_block_reason(
    db: Session, account: PublishAccount
) -> tuple[PublishHandoffReason | None, OAuthConnection | None]:
    """授权任务发外呼前的只读预检；不刷新、不尝试外发。"""
    if not account.oauth_connection_id:
        return PublishHandoffReason.OAUTH_CONNECTION_MISSING, None
    connection = db.get(OAuthConnection, account.oauth_connection_id)
    if connection is None:
        return PublishHandoffReason.OAUTH_CONNECTION_MISSING, None
    if connection.status == OAuthConnectionStatus.REVOKED:
        return PublishHandoffReason.OAUTH_CONNECTION_REVOKED, connection
    if connection.status != OAuthConnectionStatus.CONNECTED:
        return PublishHandoffReason.OAUTH_CONNECTION_ERROR, connection
    if not connection.access_token_encrypted:
        return PublishHandoffReason.OAUTH_TOKEN_MISSING, connection
    expires_at = connection.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return PublishHandoffReason.OAUTH_TOKEN_EXPIRED, connection
    return None, connection


HANDOFF_ERROR_CODES = {reason.value for reason in PublishHandoffReason}

HANDOFF_NOTES = {
    PublishHandoffReason.OAUTH_CONNECTION_MISSING: "发布账号未绑定 OAuth 连接，转人工处理",
    PublishHandoffReason.OAUTH_CONNECTION_REVOKED: "OAuth 连接已撤销，转人工重新授权",
    PublishHandoffReason.OAUTH_CONNECTION_ERROR: "OAuth 连接异常，转人工处理",
    PublishHandoffReason.OAUTH_TOKEN_MISSING: "OAuth 连接缺少服务端令牌，转人工处理",
    PublishHandoffReason.OAUTH_TOKEN_EXPIRED: "OAuth 令牌已过期，转人工重新授权",
    PublishHandoffReason.BROWSER_SESSION_REQUIRED: (
        "平台授权可用，但当前未配置浏览器登录态执行器；需扫码或验证码时转人工"
    ),
}


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

    if account_name_exists(db, ctx.project.id, channel.id, payload.account_name):
        raise ConflictError("同一渠道下发布账号名称已存在", code="publish_account_exists")

    connection = _resolve_oauth_binding(
        db,
        project_id=ctx.project.id,
        channel_id=channel.id,
        connection_id=payload.oauth_connection_id,
    )
    _ensure_oauth_not_bound_to_other_account(
        db,
        project_id=ctx.project.id,
        connection_id=payload.oauth_connection_id,
    )

    account = PublishAccount(
        project_id=ctx.project.id,
        channel_id=channel.id,
        account_name=payload.account_name,
        credential_ref=payload.credential_ref,
        oauth_connection_id=payload.oauth_connection_id,
        notes=payload.notes,
        is_active=True,
    )
    db.add(account)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "同一渠道下发布账号名称已存在，或 OAuth 连接已被其他账号绑定",
            code="publish_account_exists_or_oauth_in_use",
        ) from exc
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.account_create",
        target_type="publish_account",
        target_id=account.id,
        payload={
            "channel_id": str(channel.id),
            "account_name": account.account_name,
            "oauth_connection_id": (
                str(account.oauth_connection_id) if account.oauth_connection_id else None
            ),
        },
    )
    db.commit()
    return ok(_account_payload(account, connection=connection))


@router.get("/accounts", response_model=PagedEnvelope[PublishAccountData])
def list_accounts(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
    channel_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    total, payloads = page_accounts(
        db, ctx.project.id, channel_id=channel_id, page=page, page_size=page_size
    )
    return ok_page(payloads, page=page, page_size=page_size, total=total)


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
        if account_name_exists(db, ctx.project.id, account.channel_id, name):
            raise ConflictError("同一渠道下发布账号名称已存在", code="publish_account_exists")
        account.account_name = name

    if "credential_ref" in updates:
        account.credential_ref = updates["credential_ref"]
    connection = None
    if "oauth_connection_id" in updates:
        connection_id = updates["oauth_connection_id"]
        if connection_id is None:
            account.oauth_connection_id = None
        else:
            connection = _resolve_oauth_binding(
                db,
                project_id=ctx.project.id,
                channel_id=account.channel_id,
                connection_id=connection_id,
            )
            _ensure_oauth_not_bound_to_other_account(
                db,
                project_id=ctx.project.id,
                connection_id=connection_id,
                account_id=account.id,
            )
            account.oauth_connection_id = connection_id
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
            "同一渠道下发布账号名称已存在，或 OAuth 连接已被其他账号绑定",
            code="publish_account_exists_or_oauth_in_use",
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
            "oauth_connection_id": (
                str(account.oauth_connection_id) if account.oauth_connection_id else None
            ),
        },
    )
    db.commit()
    if connection is None and account.oauth_connection_id:
        connection = db.get(OAuthConnection, account.oauth_connection_id)
    return ok(_account_payload(account, connection=connection))


@router.delete(
    "/accounts/{account_id}",
    response_model=Envelope[PublishAccountDeleted],
)
def delete_account(
    account_id: uuid.UUID,
    ctx: ProjectContext = Depends(
        require_any_permission("publish.account_delete", "publish.execute")
    ),
    db: Session = Depends(get_db),
) -> dict:
    """受限删除误建发布账号：没有任何发布任务引用才可删。

    正常弃用账号应改为停用（is_active=false），保留历史发布任务与回执；
    只要有发布任务引用，物理删除会让历史任务悬空，统一 409 拦截。
    """
    account = require_scoped_row(
        db,
        PublishAccount,
        ctx.project.id,
        resource="publish_account",
        for_update=True,
        id=account_id,
    )
    task_count = account_task_count(db, ctx.project.id, account.id)
    if task_count:
        raise ConflictError(
            f"该发布账号仍有 {task_count} 条发布任务引用，不能删除；请改为停用。",
            code="publish_account_in_use",
        )

    channel_name = channel_display_name(db, account.channel_id)
    snapshot = {
        "account_name": account.account_name,
        "channel_id": str(account.channel_id),
        "channel_name": channel_name,
        "is_active": account.is_active,
        "notes": account.notes,
        "oauth_connection_id": (
            str(account.oauth_connection_id) if account.oauth_connection_id else None
        ),
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }
    account_name = account.account_name
    db.delete(account)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "该发布账号仍被其他数据引用，不能删除；请改为停用。",
            code="publish_account_in_use",
        ) from exc

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.account_delete",
        target_type="publish_account",
        target_id=account_id,
        payload={"account": snapshot},
    )
    db.commit()
    return ok({"id": str(account_id), "name": account_name, "deleted": True})


@router.get("/receipts", response_model=PagedEnvelope[PublishReceiptData])
def list_receipts(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    channel_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    has_budget: bool | None = None,
    has_page_approval: bool | None = None,
    q: str | None = Query(default=None, max_length=255),
) -> dict:
    total, payloads = page_receipts(
        db,
        ctx.project.id,
        channel_id=channel_id,
        task_id=task_id,
        has_budget=has_budget,
        has_page_approval=has_page_approval,
        q=q,
        page=page,
        page_size=page_size,
    )
    return ok_page(payloads, page=page, page_size=page_size, total=total)


@router.get("/tasks", response_model=PagedEnvelope[PublishTaskData])
def list_tasks(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
    status: PublishTaskStatus | None = None,
    content_type: ContentFormat | None = None,
    within_days: int | None = Query(None, ge=1, le=365),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    total, payloads = page_tasks(
        db, ctx.project.id, status=status, page=page, page_size=page_size,
        content_type=content_type, within_days=within_days,
    )
    return ok_page(payloads, page=page, page_size=page_size, total=total)


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
    previous_status = task.status
    apply_publish_status(task, PublishTaskStatus.CANCELLED)
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
    apply_publish_status(task, target_status)

    attempt_no = next_attempt_no(db, task.id)
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
    # 发布尝试成功先进入“待发布/发布中”，失败则要人工关注；回执结案才进入 published。
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
    existing = task_by_idempotency(db, ctx.project.id, idempotency_key)
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
        # pending 属于待办集合，进入时间即创建时间（ADR-01）
        entered_todo_at=datetime.now(timezone.utc),
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
        existing = task_by_idempotency(db, ctx.project.id, idempotency_key)
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


def _latest_handoff_attempt(
    db: Session, *, project_id: uuid.UUID, task_id: uuid.UUID
) -> PublishAttempt | None:
    return latest_handoff_attempt(db, project_id, task_id)


def _record_manual_handoff(
    db: Session,
    *,
    ctx: ProjectContext,
    task: PublishTask,
    version: ContentVersion,
    reason: PublishHandoffReason,
    note: str | None,
) -> PublishAttempt:
    """把任务转人工：记录 failed attempt，任务进 needs_review，不调用外部平台。

    同一任务已存在转人工记录时直接复用，避免重复点击生成多条 attempt。
    """
    if task.status not in (PublishTaskStatus.PENDING, PublishTaskStatus.NEEDS_REVIEW):
        raise ReviewStateError("只有待发布/待复核任务可以转人工")
    existing = _latest_handoff_attempt(
        db, project_id=ctx.project.id, task_id=task.id
    )
    if task.status == PublishTaskStatus.NEEDS_REVIEW and existing is not None:
        return existing

    from_status = task.status
    if from_status == PublishTaskStatus.PENDING:
        apply_publish_status(task, PublishTaskStatus.NEEDS_REVIEW)
    now = datetime.now(timezone.utc)
    previous_max = next_attempt_no(db, task.id) - 1
    attempt = PublishAttempt(
        project_id=ctx.project.id,
        task_id=task.id,
        attempt_no=(previous_max or 0) + 1,
        mode=task.publish_mode,
        result=AttemptResult.FAILED,
        error_code=reason.value,
        error_note=(note or "").strip()[:2000] or None,
        started_at=now,
        finished_at=now,
        operator_id=ctx.user.id,
    )
    db.add(attempt)
    mark_version_status(db, version, ContentStatus.NEEDS_ATTENTION)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.manual_handoff",
        target_type="publish_task",
        target_id=task.id,
        payload={
            "from_status": from_status.value,
            "to_status": task.status.value,
            "reason": reason.value,
            "note": attempt.error_note,
            "attempt_no": attempt.attempt_no,
            "external_call": False,
        },
    )
    return attempt


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
    if task.publish_mode not in (PublishMode.API, PublishMode.AUTHORIZED):
        raise ReviewStateError(
            "只有官方 API 模式或授权登录态任务可以执行；人工任务请回填回执"
        )
    if task.status not in (PublishTaskStatus.PENDING, PublishTaskStatus.NEEDS_REVIEW):
        raise ReviewStateError("只有待发布/待复核任务可以执行官方 API")

    account = require_scoped_row(
        db, PublishAccount, ctx.project.id, resource="publish_account", id=task.account_id
    )
    if not account.is_active:
        raise ReviewStateError("发布账号已停用")

    if (
        task.publish_mode == PublishMode.AUTHORIZED
        and task.status == PublishTaskStatus.NEEDS_REVIEW
    ):
        existing = _latest_handoff_attempt(
            db, project_id=ctx.project.id, task_id=task.id
        )
        if existing is not None:
            return ok(
                {
                    "task_id": str(task.id),
                    "status": task.status.value,
                    "attempt_id": str(existing.id),
                    "attempt_no": existing.attempt_no,
                    "manual_handoff": True,
                    "handoff_reason": existing.error_code,
                    "error_code": existing.error_code,
                    "error_note": existing.error_note,
                }
            )

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

    if task.publish_mode == PublishMode.AUTHORIZED:
        # 授权登录态：先做只读令牌预检；任何不可用都不外发，直接进人工队列。
        block_reason, _connection = _oauth_block_reason(db, account)
        reason = block_reason or PublishHandoffReason.BROWSER_SESSION_REQUIRED
        attempt = _record_manual_handoff(
            db,
            ctx=ctx,
            task=task,
            version=version,
            reason=reason,
            note=HANDOFF_NOTES[reason],
        )
        db.commit()
        return ok(
            {
                "task_id": str(task.id),
                "status": task.status.value,
                "attempt_id": str(attempt.id),
                "attempt_no": attempt.attempt_no,
                "manual_handoff": True,
                "handoff_reason": reason.value,
                "error_code": reason.value,
                "error_note": attempt.error_note,
            }
        )

    result = execute_wechat_publish(
        db,
        project_id=ctx.project.id,
        task_id=task.id,
        actor_id=ctx.user.id,
        digest=payload.digest,
        author=payload.author,
        thumb_media_id=payload.thumb_media_id,
        content_source_url=payload.content_source_url,
    )
    return ok(result)


@router.post(
    "/tasks/{task_id}/mass-send",
    response_model=Envelope[PublishExecuteData],
)
def mass_send_publish_task(
    task_id: uuid.UUID,
    payload: PublishWeChatExecuteRequest,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """群发一篇已审批的公众号稿子：进主页历史消息 + 推送给全部粉丝。

    与 `/execute` 的分工：`/execute` 走 `freepublish`，只产出永久链接，不进主页、不推粉丝、
    不占群发次数；这里走群发接口 `message/mass/sendall`，会占用群发次数（订阅号每天 1 次、
    服务号每月 4 次）且发布后不可撤回。因此默认由 `WECHAT_MP_MASS_SEND_ENABLED=false` 关闭，
    开启后也只允许人工逐条触发，Celery 调度器永不群发。

    群发是异步投递：提交成功只代表微信受理，任务会停在 `publishing` 并返回 `msg_id`；
    平台不返回文章 URL，需要运营拿到主页链接后用 `POST /tasks/{id}/receipts` 补回执结案。
    """
    result = execute_wechat_publish(
        db,
        project_id=ctx.project.id,
        task_id=task_id,
        actor_id=ctx.user.id,
        delivery=PublishDelivery.MASS_SEND,
        digest=payload.digest,
        author=payload.author,
        thumb_media_id=payload.thumb_media_id,
        content_source_url=payload.content_source_url,
    )
    return ok(result)


@router.post(
    "/tasks/{task_id}/handoff",
    response_model=Envelope[PublishHandoffData],
)
def handoff_publish_task(
    task_id: uuid.UUID,
    payload: PublishHandoffCreate,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """把自动发布任务转人工：记录原因与 attempt，任务进 needs_review，不重发。

    浏览器执行器遇到二维码、验证码、平台登录态失效时调用此入口；重复调用只复用
    已有转人工记录，不再生成 attempt，也不调用外部平台。
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
        raise ReviewStateError("只有待发布/待复核任务可以转人工")
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", id=task.version_id
    )
    attempt = _record_manual_handoff(
        db,
        ctx=ctx,
        task=task,
        version=version,
        reason=payload.reason,
        note=payload.note,
    )
    db.commit()
    return ok(
        {
            "task_id": str(task.id),
            "status": task.status.value,
            "attempt_id": str(attempt.id),
            "attempt_no": attempt.attempt_no,
            "reason": attempt.error_code,
            "note": attempt.error_note,
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
    channel = require_scoped_row(
        db, Channel, ctx.project.id, resource="channel", id=task.channel_id
    )
    page_approval = require_publishable_page_approval(
        db,
        project_id=ctx.project.id,
        channel=channel,
        published_url=payload.published_url,
    )

    if task.status != PublishTaskStatus.PUBLISHING:
        raise ReviewStateError("仅发布中的任务可回填回执结案；回执不明(unknown)须先经 verify")

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
        page_approval_id=page_approval.id if page_approval else None,
        receipt_payload=payload.receipt_payload,
        received_at=now,
        budget_approval_id=None,
        verified_by=ctx.user.id,
        verified_at=now,
    )
    db.add(receipt)
    apply_publish_status(task, PublishTaskStatus.PUBLISHED)
    # 回执是内容“已发布”的唯一结案信号；同步版本与当前条目状态，并推进渠道台账。
    mark_version_status(db, version, ContentStatus.PUBLISHED)
    _promote_channel_on_publish(db, project_id=ctx.project.id, channel_id=task.channel_id)
    db.flush()
    if payload.budget_approval_id is not None:
        budget = require_scoped_row(
            db,
            BudgetApproval,
            ctx.project.id,
            resource="预算申请",
            id=payload.budget_approval_id,
        )
        link_receipt_to_budget(
            db,
            project_id=ctx.project.id,
            budget=budget,
            receipt=receipt,
        )
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
            "page_approval_id": (
                str(receipt.page_approval_id) if receipt.page_approval_id else None
            ),
            "budget_approval_id": (
                str(receipt.budget_approval_id) if receipt.budget_approval_id else None
            ),
        },
    )
    db.commit()
    return ok(
        {
            "receipt_id": str(receipt.id),
            "task_id": str(task.id),
            "status": task.status.value,
            "page_approval_id": (
                str(receipt.page_approval_id) if receipt.page_approval_id else None
            ),
        }
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
    page_approval = None
    receipt: PublishReceipt | None = None
    if payload.outcome == VerifyOutcome.PUBLISHED and payload.published_url:
        channel = require_scoped_row(
            db, Channel, ctx.project.id, resource="channel", id=task.channel_id
        )
        page_approval = require_publishable_page_approval(
            db,
            project_id=ctx.project.id,
            channel=channel,
            published_url=payload.published_url,
        )
    if payload.outcome == VerifyOutcome.PUBLISHED:
        apply_publish_status(task, PublishTaskStatus.PUBLISHED)
        if payload.published_url:
            receipt = PublishReceipt(
                project_id=ctx.project.id,
                task_id=task.id,
                published_url=payload.published_url,
                page_approval_id=page_approval.id if page_approval else None,
                receipt_payload=payload.receipt_payload,
                received_at=now,
                budget_approval_id=None,
                verified_by=ctx.user.id,
                verified_at=now,
            )
            db.add(receipt)
        content_target = ContentStatus.PUBLISHED
    else:
        apply_publish_status(task, PublishTaskStatus.PENDING)
        content_target = ContentStatus.NEEDS_ATTENTION

    mark_version_status(db, version, content_target)
    if task.status == PublishTaskStatus.PUBLISHED:
        _promote_channel_on_publish(db, project_id=ctx.project.id, channel_id=task.channel_id)
    db.flush()
    if (
        task.status == PublishTaskStatus.PUBLISHED
        and payload.published_url
        and payload.budget_approval_id is not None
    ):
        budget = require_scoped_row(
            db,
            BudgetApproval,
            ctx.project.id,
            resource="预算申请",
            id=payload.budget_approval_id,
        )
        link_receipt_to_budget(
            db,
            project_id=ctx.project.id,
            budget=budget,
            receipt=receipt,
        )
    if task.status == PublishTaskStatus.PUBLISHED and payload.published_url:
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
            "task_status": task.status.value,
            "content_status": version.status.value,
            "page_approval_id": (
                str(receipt.page_approval_id)
                if payload.published_url
                and receipt is not None
                and receipt.page_approval_id
                else None
            ),
            "budget_approval_id": (
                str(receipt.budget_approval_id)
                if payload.published_url
                and receipt is not None
                and receipt.budget_approval_id
                else None
            ),
        },
    )
    db.commit()
    return ok(
        {
            "task_id": str(task.id),
            "status": task.status.value,
            "receipt_id": (
                str(receipt.id)
                if task.status == PublishTaskStatus.PUBLISHED
                and payload.published_url
                and receipt is not None
                else None
            ),
            "page_approval_id": (
                str(receipt.page_approval_id)
                if task.status == PublishTaskStatus.PUBLISHED
                and payload.published_url
                and receipt is not None
                and receipt.page_approval_id
                else None
            ),
        }
    )

"""发布执行：微信公众号官方 API 的领域实现。

两处入口共用同一段逻辑，避免「手动点一次」和「到点自动发」两套代码漂移：
- HTTP `POST /publish/tasks/{id}/execute`
- Celery beat `geo.publish.schedule`

口径不变：
- 只有 `publish_mode=api` + 公众号渠道 + pending/needs_review 可自动执行；
- 明确拒绝（errcode/4xx）落 failed；超时/5xx 落 unknown，禁止自动重试；
- 先落 publishing 再发外部请求，进程中途崩溃不会退回 pending 被重发。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.credentials import read_credential_env
from app.core.errors import ReviewStateError, ServiceUnavailableError
from app.models import (
    Channel,
    ContentItem,
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
)
from app.services.audit import record_audit
from app.services.citation_attribution import backfill_channel_for_url
from app.services.content_status import mark_version_status, sync_current_item_status
from app.services.project_scope import require_scoped_row
from app.services.publish_listing import (
    channel_row as channel_by_id,
    latest_content_review,
    next_attempt_no,
)
from app.services.state_machine import ensure_channel_transition, ensure_content_transition
from app.services.todo_clock import apply_publish_status
from app.services.wechat_publisher import (
    WeChatOfficialPublisher,
    WeChatPublisherError,
    build_wechat_digest,
    render_wechat_html,
)

logger = logging.getLogger(__name__)


def promote_channel_on_publish(
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
    channel = channel_by_id(db, project_id, channel_id)
    if channel is None:
        return
    if channel.status in {ChannelStatus.CANDIDATE, ChannelStatus.REVIEW_PENDING}:
        channel.status = ensure_channel_transition(channel.status, ChannelStatus.PUBLISHED)


def guard_version_hash(
    db: Session,
    version: ContentVersion,
    *,
    project_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> None:
    """hash 守卫：比对最新审批快照与当前正文 hash；不一致退回 pending_review 并写审计，抛 409。

    覆盖建任务 / 回执 / verify / 自动执行四个写入点；不做全表巡检。回落经
    CONTENT_TRANSITIONS 状态机校验，不走旁路。`actor_id=None` 表示系统触发。
    """
    latest_review = latest_content_review(db, version.id)
    if latest_review is None:
        return
    if latest_review.content_hash_snapshot == version.content_hash:
        return
    version.status = ensure_content_transition(version.status, ContentStatus.PENDING_REVIEW)
    item = db.get(ContentItem, version.item_id)
    if item is not None and item.current_version_id == version.id:
        # 条目状态是「当前版本」的镜像，不是独立迁移：版本刚过完 ensure_content_transition，
        # 这里跟着写同一个值，保证列表页的条目状态与版本状态不会分叉。
        sync_current_item_status(item, version)
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


def execute_wechat_publish(
    db: Session,
    *,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    digest: str | None = None,
    author: str | None = None,
    thumb_media_id: str | None = None,
    content_source_url: str | None = None,
) -> dict:
    """执行一次公众号发布：草稿 → 发布 → 能拿到 URL 就结案。

    `actor_id=None` 表示由调度器触发；审计与尝试记录照写，只是没有具体操作人。
    """
    task = require_scoped_row(
        db,
        PublishTask,
        project_id,
        resource="publish_task",
        for_update=True,
        id=task_id,
    )
    if task.publish_mode != PublishMode.API:
        raise ReviewStateError("只有官方 API 模式的任务可以自动执行；授权登录态与人工任务走转人工")
    if task.status not in (PublishTaskStatus.PENDING, PublishTaskStatus.NEEDS_REVIEW):
        raise ReviewStateError("只有待发布/待复核任务可以执行官方 API")

    account = require_scoped_row(
        db, PublishAccount, project_id, resource="publish_account", id=task.account_id
    )
    if not account.is_active:
        raise ReviewStateError("发布账号已停用")

    version = require_scoped_row(
        db, ContentVersion, project_id, resource="content_version", id=task.version_id
    )
    item = require_scoped_row(
        db, ContentItem, project_id, resource="content_item", id=version.item_id
    )
    if item.kind != ContentKind.CHANNEL:
        raise ReviewStateError("只有渠道稿可以执行发布")
    if item.current_version_id != version.id:
        raise ReviewStateError("只能发布当前内容版本")
    guard_version_hash(db, version, project_id=project_id, actor_id=actor_id)
    if version.status not in (ContentStatus.APPROVED, ContentStatus.PENDING_PUBLISH):
        raise ReviewStateError("只有审批通过或待发布的版本可以执行发布")

    channel = require_scoped_row(
        db, Channel, project_id, resource="channel", id=task.channel_id
    )
    if channel.code.strip() != settings.wechat_mp_channel_code.strip():
        raise ReviewStateError(
            f"当前只接入微信公众号官方 API，渠道 {channel.code} 尚未支持"
        )

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
    digest_text = (digest or "").strip() or build_wechat_digest(version.body)
    author_text = (author or settings.wechat_mp_author or "").strip()
    thumb = (
        thumb_media_id or settings.wechat_mp_default_thumb_media_id or ""
    ).strip()

    apply_publish_status(task, PublishTaskStatus.PUBLISHING)
    now = datetime.now(timezone.utc)
    attempt_no = next_attempt_no(db, task.id)
    attempt = PublishAttempt(
        project_id=project_id,
        task_id=task.id,
        attempt_no=attempt_no,
        mode=PublishMode.API,
        result=AttemptResult.UNKNOWN,
        started_at=now,
        operator_id=actor_id,
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
                author=author_text,
                digest=digest_text,
                content_source_url=content_source_url or "",
                thumb_media_id=thumb,
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
            apply_publish_status(task, PublishTaskStatus.UNKNOWN)
        else:
            attempt.result = AttemptResult.FAILED
            apply_publish_status(task, PublishTaskStatus.FAILED)
        mark_version_status(db, version, ContentStatus.NEEDS_ATTENTION)
    else:
        assert result is not None
        attempt.result = AttemptResult.SUCCESS
        task.external_task_id = (result.publish_id or result.media_id)[:128]
        if result.article_url:
            apply_publish_status(task, PublishTaskStatus.PUBLISHED)
            receipt = PublishReceipt(
                project_id=project_id,
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
                verified_by=actor_id,
                verified_at=datetime.now(timezone.utc),
            )
            db.add(receipt)
            mark_version_status(db, version, ContentStatus.PUBLISHED)
            promote_channel_on_publish(
                db, project_id=project_id, channel_id=task.channel_id
            )
            db.flush()
            backfill_channel_for_url(db, project_id, result.article_url, task.channel_id)
        else:
            # 已提交但还没拿到文章 URL：保持 publishing，运营拿到 URL 后补回执结案。
            # 同状态迁移是幂等的，但仍然过一次状态机，避免这条分支变成绕过口。
            apply_publish_status(task, PublishTaskStatus.PUBLISHING)
            mark_version_status(db, version, ContentStatus.PENDING_PUBLISH)

    db.flush()
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
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
            "trigger": "scheduler" if actor_id is None else "manual",
        },
    )
    db.commit()
    return {
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


def due_wechat_tasks(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 50,
    project_id: uuid.UUID | None = None,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """到期可自动执行的公众号任务：显式排期 + api 模式 + 账号有效 + 公众号渠道。

    只返回 `(task_id, project_id)`；状态与内容校验仍在执行函数里做，
    因为查询到执行之间可能有人工操作（取消、改模式、补回执）。
    """
    now = now or datetime.now(timezone.utc)
    stmt = (
        select(PublishTask.id, PublishTask.project_id)
        .join(PublishAccount, PublishTask.account_id == PublishAccount.id)
        .join(Channel, PublishTask.channel_id == Channel.id)
        .where(
            PublishTask.publish_mode == PublishMode.API,
            PublishTask.status == PublishTaskStatus.PENDING,
            PublishTask.scheduled_at.is_not(None),
            PublishTask.scheduled_at <= now,
            PublishAccount.is_active.is_(True),
            Channel.code == settings.wechat_mp_channel_code,
            Channel.is_active.is_(True),
        )
        .order_by(PublishTask.scheduled_at)
        .limit(max(1, min(limit, 200)))
    )
    if project_id is not None:
        stmt = stmt.where(PublishTask.project_id == project_id)
    return list(db.execute(stmt).all())


def run_due_wechat_publishes(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 50,
    project_id: uuid.UUID | None = None,
) -> dict:
    """调度器入口：逐条执行到期任务，单条失败不影响同批其余任务。"""
    if not settings.publish_auto_execute_enabled:
        return {"enabled": False, "due": 0, "published": 0, "failed": 0, "unknown": 0, "skipped": 0, "errors": []}

    rows = due_wechat_tasks(db, now=now, limit=limit, project_id=project_id)
    # 结束只读事务，避免把扫描事务拖到外部调用结束。
    db.commit()
    stats = {
        "enabled": True,
        "due": len(rows),
        "published": 0,
        "failed": 0,
        "unknown": 0,
        "skipped": 0,
        "errors": [],
    }
    for task_id, task_project_id in rows:
        try:
            result = execute_wechat_publish(
                db,
                project_id=task_project_id,
                task_id=task_id,
                actor_id=None,
            )
        except Exception as exc:  # noqa: BLE001 - 调度器不能因单条失败中断整批
            db.rollback()
            status = getattr(getattr(exc, "status_code", None), "value", None)
            logger.warning(
                "自动发稿跳过 task=%s code=%s: %s",
                task_id,
                getattr(exc, "code", None) or status or type(exc).__name__,
                exc,
            )
            stats["skipped"] += 1
            stats["errors"].append(
                {
                    "task_id": str(task_id),
                    "error_code": getattr(exc, "code", None) or type(exc).__name__,
                    "error": str(exc)[:300],
                }
            )
            continue
        final = result["status"]
        if final == PublishTaskStatus.PUBLISHED.value:
            stats["published"] += 1
        elif final == PublishTaskStatus.FAILED.value:
            stats["failed"] += 1
        elif final == PublishTaskStatus.UNKNOWN.value:
            stats["unknown"] += 1
        else:
            stats["skipped"] += 1
    if rows:
        # 只在真有到期任务时打一条汇总，避免每分钟空扫刷日志。
        logger.info(
            "自动发稿批次完成 due=%s published=%s failed=%s unknown=%s skipped=%s",
            stats["due"],
            stats["published"],
            stats["failed"],
            stats["unknown"],
            stats["skipped"],
        )
    return stats

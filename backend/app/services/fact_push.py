"""事实推送（G9）：把**已核准**事实推到 EEAT 信源，并留下可核对的推送记录。

三条口径（改代码前先看）：

1. **只推已核准事实**：`approval_status != approved` 一律拒。事实库的价值全在
   「这句是核对过的」，把草稿推出去等于把草稿当公告。
2. **推送不等于发布**：百科方向只生成**草稿词条**，之后仍要走
   `ENCYCLOPEDIA_TRANSITIONS`（提交 → 人工审核 → 登记外链），系统不代第三方平台发布；
   webhook 方向只把事实 JSON 送达对方并记录回执，成功失败都留痕，失败可重试。
3. **幂等**：同一 `(fact, target_type, target_ref)` 只保留一条记录；已 pending / sent
   的重复请求直接返回原记录、不重复外发——外发重复的代价比少发一次高得多。

不使用「推送成功 = 事实生效」这种说法：外发是否真被对方采用，只有回执与后续引用能说明。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ResourceMissingError
from app.models import DistributionPush, EncyclopediaEntry, Fact
from app.models.enums import (
    EncyclopediaStatus,
    FactStatus,
    PushStatus,
    PushTargetType,
)
from app.services.state_machine import ensure_push_transition

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 8
_SAFE_KEY = re.compile(r"[^0-9A-Za-z\u4e00-\u9fa5-]+")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_target(push_target: PushTargetType, target_ref: str | None) -> str:
    """把目标归一成稳定字符串，用作幂等键的一部分。

    - 百科方向 target_ref 是平台名（baidu_baike / other…），留空默认 other；
    - webhook 方向 target_ref 必须是 http(s) 地址，其它一律拒（避免把推送写成任意协议调用）。
    """
    ref = (target_ref or "").strip()
    if push_target == PushTargetType.ENCYCLOPEDIA:
        return ref or "other"
    if not ref:
        raise ConflictError("webhook 推送必须提供目标地址", code="push_target_missing")
    parsed = urlparse(ref)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConflictError("webhook 目标必须是 http(s) 地址", code="push_target_invalid")
    return ref


def _idempotency_key(
    fact_id: uuid.UUID, push_target: PushTargetType, target_ref: str
) -> str:
    raw = f"{fact_id}|{push_target.value}|{target_ref}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _entry_slug(fact: Fact) -> str:
    base = _SAFE_KEY.sub("-", fact.fact_key).strip("-")[:80] or "fact"
    digest = hashlib.sha256(str(fact.id).encode("utf-8")).hexdigest()[:8]
    return f"fact-{base}-{digest}"[:128]


def _push_to_encyclopedia(db: Session, push: DistributionPush, fact: Fact) -> None:
    """生成一条草稿词条；词条本身仍要提交与审核，这里只是把事实搬进起草区。"""
    entry = EncyclopediaEntry(
        project_id=push.project_id,
        slug=_entry_slug(fact),
        title=fact.fact_key,
        platform=push.target_ref or "other",
        summary=fact.fact_value[:280],
        body=fact.fact_value,
        references=(
            [{"title": f"{fact.fact_key}（事实库来源）", "url": fact.source_url, "note": "由事实库推送生成"}]
            if fact.source_url
            else []
        ),
        # 词条表没有 created_by 字段（作者信息由 audit 留痕），这里不传
        status=EncyclopediaStatus.DRAFT,
    )
    db.add(entry)
    db.flush()
    push.external_ref = str(entry.id)
    push.response_payload = {"entry_id": str(entry.id), "platform": push.target_ref, "fact_id": str(fact.id)}
    push.error = None
    push.status = ensure_push_transition(push.status, PushStatus.SENT)
    push.sent_at = _now()


def _push_to_webhook(db: Session, push: DistributionPush, fact: Fact, url: str) -> None:
    payload = {
        "event": "geo_fact_push",
        "project_id": str(push.project_id),
        "fact": {
            "id": str(fact.id),
            "type": fact.fact_type.value,
            "key": fact.fact_key,
            "value": fact.fact_value,
            "source_url": fact.source_url,
            "version_no": fact.version_no,
            "approved_at": fact.approved_at.isoformat() if fact.approved_at else None,
        },
        "idempotency_key": push.idempotency_key,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT_SECONDS) as response:  # noqa: S310 - 部署方配置的目标
            status_code = response.status
            body = response.read().decode("utf-8", errors="replace")[:2000]
    except Exception as exc:  # noqa: BLE001 - 外发失败要落库留痕，不能让异常吞掉记录
        logger.warning("fact push failed", extra={"fields": {"target": url, "error": str(exc)}})
        push.status = ensure_push_transition(push.status, PushStatus.FAILED)
        push.error = f"{type(exc).__name__}: {exc}"[:500]
        push.response_payload = None
        return
    push.status = ensure_push_transition(push.status, PushStatus.SENT)
    push.error = None
    push.sent_at = _now()
    push.external_ref = str(status_code)
    push.response_payload = {"status_code": status_code, "body": body}


def dispatch_push(db: Session, push: DistributionPush, fact: Fact) -> DistributionPush:
    """执行一次外发；push 必须处于 pending（重试时由 retry_push 先复位）。"""
    push.attempt_count += 1
    push.last_attempt_at = _now()
    if push.target_type == PushTargetType.ENCYCLOPEDIA:
        _push_to_encyclopedia(db, push, fact)
    else:
        _push_to_webhook(db, push, fact, push.target_ref)
    db.flush()
    return push


def push_fact(
    db: Session,
    *,
    project_id: uuid.UUID,
    fact: Fact,
    target_type: PushTargetType,
    target_ref: str | None,
    actor_id: uuid.UUID | None,
) -> tuple[DistributionPush, bool]:
    """返回 (推送记录, 是否新建)。已存在且未失败时不重复外发。"""
    if fact.project_id != project_id:
        raise ResourceMissingError("事实不存在或不属于当前项目", code="fact_missing")
    if fact.approval_status != FactStatus.APPROVED:
        raise ConflictError("只有已核准的事实能推送", code="fact_not_approved")
    normalized = normalize_target(target_type, target_ref)
    existing = db.scalar(
        select(DistributionPush).where(
            DistributionPush.project_id == project_id,
            DistributionPush.fact_id == fact.id,
            DistributionPush.target_type == target_type,
            DistributionPush.target_ref == normalized,
        )
    )
    if existing is not None and existing.status in (PushStatus.PENDING, PushStatus.SENT):
        return existing, False
    if existing is None:
        push = DistributionPush(
            project_id=project_id,
            fact_id=fact.id,
            target_type=target_type,
            target_ref=normalized,
            status=PushStatus.PENDING,
            idempotency_key=_idempotency_key(fact.id, target_type, normalized),
            created_by=actor_id,
        )
        db.add(push)
        db.flush()
    else:
        push = existing
        push.status = ensure_push_transition(push.status, PushStatus.PENDING)
        push.created_by = actor_id
    dispatch_push(db, push, fact)
    return push, True


def retry_push(db: Session, *, project_id: uuid.UUID, push_id: uuid.UUID) -> DistributionPush:
    push = db.scalar(
        select(DistributionPush).where(
            DistributionPush.id == push_id, DistributionPush.project_id == project_id
        )
    )
    if push is None:
        raise ResourceMissingError("推送记录不存在", code="push_missing")
    if push.status != PushStatus.FAILED:
        raise ConflictError("只有失败的推送能重试", code="push_not_retryable")
    fact = db.get(Fact, push.fact_id)
    if fact is None:
        raise ResourceMissingError("推送关联的事实已不存在", code="fact_missing")
    if fact.approval_status != FactStatus.APPROVED:
        raise ConflictError("事实已不再处于已核准状态，不能重试推送", code="fact_not_approved")
    push.status = ensure_push_transition(push.status, PushStatus.PENDING)
    dispatch_push(db, push, fact)
    return push


def page_pushes(
    db: Session,
    project_id: uuid.UUID,
    *,
    fact_id: uuid.UUID | None = None,
    status: PushStatus | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[DistributionPush], int]:
    filters = [DistributionPush.project_id == project_id]
    if fact_id is not None:
        filters.append(DistributionPush.fact_id == fact_id)
    if status is not None:
        filters.append(DistributionPush.status == status)
    rows = list(
        db.scalars(
            select(DistributionPush).where(*filters)
            .order_by(DistributionPush.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    )
    total = db.scalar(
        select(func.count()).select_from(DistributionPush).where(*filters)
    ) or 0
    return rows, total


def push_payload(push: DistributionPush) -> dict[str, Any]:
    return {
        "id": str(push.id),
        "fact_id": str(push.fact_id),
        "target_type": push.target_type.value,
        "target_ref": push.target_ref,
        "status": push.status.value,
        "attempt_count": push.attempt_count,
        "external_ref": push.external_ref,
        "error": push.error,
        "response_payload": push.response_payload,
        "sent_at": push.sent_at.isoformat() if push.sent_at else None,
        "last_attempt_at": push.last_attempt_at.isoformat() if push.last_attempt_at else None,
        "created_at": push.created_at.isoformat() if push.created_at else None,
    }

"""工作台跨模块待办的唯一读取口径。

六类待办在数据库侧聚合，计数不受列表分页限制；`today/week` 一律按
“进入当前待处理状态的时间”落在左闭右开区间内，避免把未来记录算进来。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    AlertEvent,
    ContentItem,
    ContentVersion,
    Fact,
    KnowledgeCandidateFact,
    KnowledgeDocument,
    Material,
    MonitoringTask,
    PublishAccount,
    PublishTask,
    Question,
    QuestionVersion,
    User,
)
from app.models.enums import (
    AlertEventStatus,
    AlertSeverity,
    ContentStatus,
    FactStatus,
    KnowledgeCandidateStatus,
    KnowledgeParseStatus,
    PublishTaskStatus,
    TaskStatus,
)

TodoRange = Literal["today", "week", "all"]
_RANGE_VALUES: tuple[TodoRange, ...] = ("today", "week", "all")

_DOC_SUFFIXES = (".pdf", ".doc", ".docx", ".txt", ".md", ".xlsx", ".pptx")


@dataclass(frozen=True)
class TodoWindow:
    """按请求方本地时区划出的今天/本周窗口，统一左闭右开。"""

    today_start: datetime
    today_end: datetime
    week_start: datetime
    week_end: datetime


def _window(now: datetime, tz_offset_minutes: int) -> TodoWindow:
    tz = timezone(timedelta(minutes=tz_offset_minutes))
    local_now = now.astimezone(tz)
    today_start = datetime.combine(local_now.date(), time.min, tzinfo=tz)
    week_start = today_start - timedelta(days=local_now.weekday())
    return TodoWindow(
        today_start=today_start,
        today_end=today_start + timedelta(days=1),
        week_start=week_start,
        week_end=week_start + timedelta(days=7),
    )


def _range_counts(
    db: Session,
    count_stmt,
    at_col,
    window: TodoWindow,
) -> dict[str, int]:
    return {
        "today": int(
            db.scalar(
                count_stmt.where(at_col >= window.today_start, at_col < window.today_end)
            )
            or 0
        ),
        "week": int(
            db.scalar(
                count_stmt.where(at_col >= window.week_start, at_col < window.week_end)
            )
            or 0
        ),
        "all": int(db.scalar(count_stmt) or 0),
    }


def _range_filter(at_col, range_value: TodoRange, window: TodoWindow):
    if range_value == "all":
        return None
    start, end = (
        (window.today_start, window.today_end)
        if range_value == "today"
        else (window.week_start, window.week_end)
    )
    return and_(at_col >= start, at_col < end)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _short(value: str | None, limit: int = 42) -> str:
    text = (value or "").strip().replace("\n", " ")
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _item(
    *,
    key: str,
    group: str,
    title: str,
    meta: str,
    section: str,
    tone: str,
    badge: str,
    at: datetime | None,
) -> dict[str, Any]:
    return {
        "key": key,
        "group": group,
        "title": title,
        "meta": meta,
        "section": section,
        "tone": tone,
        "badge": badge,
        "at": _iso(at),
    }


def _content_reviews(db: Session, project_id: uuid.UUID, window: TodoWindow, range_value: TodoRange, limit: int):
    at_col = func.coalesce(ContentVersion.submitted_at, ContentVersion.created_at)
    base = [
        ContentVersion.project_id == project_id,
        ContentVersion.status == ContentStatus.PENDING_REVIEW,
        ContentVersion.id == ContentItem.current_version_id,
        ContentItem.project_id == project_id,
    ]
    count_stmt = select(func.count()).select_from(ContentVersion).join(
        ContentItem, ContentItem.id == ContentVersion.item_id
    ).where(*base)
    counts = _range_counts(db, count_stmt, at_col, window)
    range_clause = _range_filter(at_col, range_value, window)
    stmt = (
        select(ContentVersion.id, ContentItem.title, User.display_name, ContentVersion.version_no, at_col)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .outerjoin(User, User.id == func.coalesce(ContentVersion.submitted_by, ContentVersion.created_by))
        .where(*base, *([range_clause] if range_clause is not None else []))
        .order_by(at_col.desc().nullslast(), ContentVersion.id.desc())
        .limit(limit)
    )
    items = [
        _item(
            key=f"review-{row[0]}",
            group="内容审核",
            title=row[1] or "未命名内容",
            meta=f"{row[2] or '提交人未知'} · v{row[3]}",
            section="reviews",
            tone="amber",
            badge="待审核",
            at=row[4],
        )
        for row in db.execute(stmt).all()
    ]
    return counts, items


def _publish_queue(db: Session, project_id: uuid.UUID, window: TodoWindow, range_value: TodoRange, limit: int):
    at_col = func.coalesce(PublishTask.updated_at, PublishTask.created_at)
    base = [
        PublishTask.project_id == project_id,
        PublishTask.status.in_([PublishTaskStatus.PENDING, PublishTaskStatus.NEEDS_REVIEW]),
    ]
    count_stmt = select(func.count()).select_from(PublishTask).where(*base)
    counts = _range_counts(db, count_stmt, at_col, window)
    range_clause = _range_filter(at_col, range_value, window)
    stmt = (
        select(PublishTask.id, PublishTask.serial_no, PublishTask.status, ContentItem.title, PublishAccount.account_name, at_col)
        .join(ContentVersion, ContentVersion.id == PublishTask.version_id)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .outerjoin(PublishAccount, PublishAccount.id == PublishTask.account_id)
        .where(*base, *([range_clause] if range_clause is not None else []))
        .order_by(at_col.desc().nullslast(), PublishTask.id.desc())
        .limit(limit)
    )
    items = [
        _item(
            key=f"publish-{row[0]}",
            group="发布队列",
            title=row[3] or f"发布任务 #{row[1]}",
            meta=f"发布任务 #{row[1]}{f' · {row[4]}' if row[4] else ''}",
            section="publishing",
            tone="blue",
            badge="待复核" if row[2] == PublishTaskStatus.NEEDS_REVIEW else "待发布",
            at=row[5],
        )
        for row in db.execute(stmt).all()
    ]
    return counts, items


def _collect_failures(db: Session, project_id: uuid.UUID, window: TodoWindow, range_value: TodoRange, limit: int):
    at_col = MonitoringTask.updated_at
    base = [
        MonitoringTask.project_id == project_id,
        MonitoringTask.status.in_([TaskStatus.FAILED, TaskStatus.UNCERTAIN]),
    ]
    count_stmt = select(func.count()).select_from(MonitoringTask).where(*base)
    counts = _range_counts(db, count_stmt, at_col, window)
    range_clause = _range_filter(at_col, range_value, window)
    stmt = (
        select(MonitoringTask.id, MonitoringTask.serial_no, MonitoringTask.status, Question.title, AiEngine.name, at_col)
        .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
        .join(Question, Question.id == QuestionVersion.question_id)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(*base, *([range_clause] if range_clause is not None else []))
        .order_by(at_col.desc().nullslast(), MonitoringTask.id.desc())
        .limit(limit)
    )
    items = [
        _item(
            key=f"task-{row[0]}",
            group="采集失败",
            title=row[3] or "监测任务",
            meta=f"{row[4]} · 任务 #{row[1]} · {'需复核' if row[2] == TaskStatus.UNCERTAIN else '失败'}",
            section="monitoring",
            tone="red" if row[2] == TaskStatus.FAILED else "amber",
            badge="失败" if row[2] == TaskStatus.FAILED else "需复核",
            at=row[5],
        )
        for row in db.execute(stmt).all()
    ]
    return counts, items


def _fact_queue(db: Session, project_id: uuid.UUID, window: TodoWindow, range_value: TodoRange, limit: int):
    at_col = Fact.updated_at
    missing_source = func.coalesce(
        func.nullif(Fact.source_document, ""), func.nullif(Fact.source_url, "")
    ).is_(None)
    base = [
        Fact.project_id == project_id,
        or_(
            Fact.approval_status.in_([FactStatus.DRAFT, FactStatus.PENDING_REVIEW]),
            missing_source,
        ),
    ]
    count_stmt = select(func.count()).select_from(Fact).where(*base)
    counts = _range_counts(db, count_stmt, at_col, window)
    range_clause = _range_filter(at_col, range_value, window)
    stmt = (
        select(Fact.id, Fact.fact_key, Fact.fact_value, Fact.approval_status, missing_source, at_col)
        .where(*base, *([range_clause] if range_clause is not None else []))
        .order_by(at_col.desc().nullslast(), Fact.id.desc())
        .limit(limit)
    )
    items = [
        _item(
            key=f"fact-{row[0]}",
            group="事实审批",
            title=row[1],
            meta=(
                f"{'草稿待提交' if row[3] == FactStatus.DRAFT else '待审批'}"
                f"{' · 缺来源' if row[4] else ''} · {_short(row[2], 24)}"
            ),
            section="facts",
            tone="amber",
            badge="草稿" if row[3] == FactStatus.DRAFT else "待审批",
            at=row[5],
        )
        for row in db.execute(stmt).all()
    ]
    return counts, items


def _knowledge_queue(db: Session, project_id: uuid.UUID, window: TodoWindow, range_value: TodoRange, limit: int):
    material_at = Material.created_at
    material_ready = KnowledgeDocument.parse_status == KnowledgeParseStatus.READY
    material_base = [
        Material.project_id == project_id,
        or_(*[func.lower(Material.file_name).like(f"%{suffix}") for suffix in _DOC_SUFFIXES]),
        or_(KnowledgeDocument.id.is_(None), KnowledgeDocument.parse_status != KnowledgeParseStatus.READY),
    ]
    material_count = select(func.count()).select_from(Material).outerjoin(
        KnowledgeDocument, KnowledgeDocument.material_id == Material.id
    ).where(*material_base)
    material_counts = _range_counts(db, material_count, material_at, window)
    material_clause = _range_filter(material_at, range_value, window)
    material_stmt = (
        select(Material.id, Material.title, Material.file_name, KnowledgeDocument.parse_status, material_at)
        .outerjoin(KnowledgeDocument, KnowledgeDocument.material_id == Material.id)
        .where(*material_base, *([material_clause] if material_clause is not None else []))
        .order_by(material_at.desc().nullslast(), Material.id.desc())
        .limit(limit)
    )
    material_items = [
        _item(
            key=f"doc-{row[0]}",
            group="知识解析",
            title=row[1] or row[2],
            meta="解析失败" if row[3] == KnowledgeParseStatus.FAILED else "待解析",
            section="knowledge",
            tone="red" if row[3] == KnowledgeParseStatus.FAILED else "amber",
            badge="解析失败" if row[3] == KnowledgeParseStatus.FAILED else "待解析",
            at=row[4],
        )
        for row in db.execute(material_stmt).all()
    ]

    candidate_at = KnowledgeCandidateFact.created_at
    candidate_base = [
        KnowledgeCandidateFact.project_id == project_id,
        KnowledgeCandidateFact.status == KnowledgeCandidateStatus.SUGGESTED,
    ]
    candidate_count = select(func.count()).select_from(KnowledgeCandidateFact).where(*candidate_base)
    candidate_counts = _range_counts(db, candidate_count, candidate_at, window)
    candidate_clause = _range_filter(candidate_at, range_value, window)
    candidate_stmt = (
        select(KnowledgeCandidateFact.id, KnowledgeCandidateFact.claim_text, Material.title, candidate_at)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeCandidateFact.document_id)
        .outerjoin(Material, Material.id == KnowledgeDocument.material_id)
        .where(*candidate_base, *([candidate_clause] if candidate_clause is not None else []))
        .order_by(candidate_at.desc().nullslast(), KnowledgeCandidateFact.id.desc())
        .limit(limit)
    )
    candidate_items = [
        _item(
            key=f"candidate-{row[0]}",
            group="知识解析",
            title=_short(row[1], 60),
            meta=f"候选事实待确认 · {row[2] or '来源文档'}",
            section="knowledge",
            tone="blue",
            badge="待确认",
            at=row[3],
        )
        for row in db.execute(candidate_stmt).all()
    ]

    counts = {key: material_counts[key] + candidate_counts[key] for key in _RANGE_VALUES}
    items = sorted(material_items + candidate_items, key=lambda item: item["at"] or "", reverse=True)[:limit]
    return counts, items


def _alert_queue(db: Session, project_id: uuid.UUID, window: TodoWindow, range_value: TodoRange, limit: int):
    at_col = func.coalesce(AlertEvent.last_seen_at, AlertEvent.triggered_at)
    base = [AlertEvent.project_id == project_id, AlertEvent.status == AlertEventStatus.OPEN]
    count_stmt = select(func.count()).select_from(AlertEvent).where(*base)
    counts = _range_counts(db, count_stmt, at_col, window)
    range_clause = _range_filter(at_col, range_value, window)
    stmt = (
        select(AlertEvent.id, AlertEvent.title, AlertEvent.message, AlertEvent.severity, at_col)
        .where(*base, *([range_clause] if range_clause is not None else []))
        .order_by(at_col.desc().nullslast(), AlertEvent.id.desc())
        .limit(limit)
    )
    items = [
        _item(
            key=f"alert-{row[0]}",
            group="异常预警",
            title=row[1],
            meta=(
                f"{'严重' if row[3] == AlertSeverity.CRITICAL else '警告' if row[3] == AlertSeverity.WARNING else '提示'}"
                f" · {_short(row[2], 32)}"
            ),
            section="alerts",
            tone="red" if row[3] == AlertSeverity.CRITICAL else "amber",
            badge="严重" if row[3] == AlertSeverity.CRITICAL else "警告" if row[3] == AlertSeverity.WARNING else "提示",
            at=row[4],
        )
        for row in db.execute(stmt).all()
    ]
    return counts, items


def todo_snapshot(
    db: Session,
    project_id: uuid.UUID,
    *,
    range_value: TodoRange = "all",
    tz_offset_minutes: int = 480,
    limit: int = 20,
    permissions: frozenset[str] | set[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """返回项目内六类待办的精确计数与分组预览。

    `permissions` 传入时按模块能力收窄，避免把无权查看的队列暴露给调用方；
    `None` 表示调用方已经完成项目级门禁，保留全部分组（只用于内部测试）。
    """
    now = now or datetime.now(timezone.utc)
    window = _window(now, tz_offset_minutes)
    allowed = {"content.read", "publish.read", "monitoring.read"} if permissions is None else set(permissions)

    groups: list[dict[str, Any]] = []
    total = {key: 0 for key in _RANGE_VALUES}

    def add(key: str, label: str, section: str, required: str, loader) -> None:
        if required not in allowed:
            return
        counts, items = loader(db, project_id, window, range_value, limit)
        for range_key in _RANGE_VALUES:
            total[range_key] += counts[range_key]
        groups.append(
            {
                "key": key,
                "label": label,
                "section": section,
                "counts": counts,
                "total": counts[range_value],
                "items": items,
            }
        )

    add("reviews", "内容审核", "reviews", "content.read", _content_reviews)
    add("publish", "发布队列", "publishing", "publish.read", _publish_queue)
    add("collect", "采集失败", "monitoring", "monitoring.read", _collect_failures)
    add("facts", "事实审批", "facts", "content.read", _fact_queue)
    add("knowledge", "知识解析", "knowledge", "content.read", _knowledge_queue)
    add("alerts", "异常预警", "alerts", "content.read", _alert_queue)

    window_payload = None
    if range_value != "all":
        start, end = (
            (window.today_start, window.today_end)
            if range_value == "today"
            else (window.week_start, window.week_end)
        )
        window_payload = {"start": start.isoformat(), "end": end.isoformat()}

    return {
        "project_id": str(project_id),
        "range": range_value,
        "timezone_offset_minutes": tz_offset_minutes,
        "generated_at": now.isoformat(),
        "window": window_payload,
        "counts": total,
        "groups": groups,
    }

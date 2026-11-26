"""待办周期时间的唯一写入口（R-01 / ADR-01）。

语义（唯一权威表述，模型注释、迁移注释、文档三处同源）：

    entered_todo_at 记录对象"本次进入当前待办集合"的起始时刻。
    对象持续属于该待办集合期间，普通字段更新、集合内部迁移、重试与数据刷新
    均不得刷新该值；退出集合按实体规则处理（专用周期字段置 NULL，复用业务字段
    保留原值）；再次进入时记录新的进入时间。

因此本模块只做一件事：判定"跨越集合边界"，并在跨越时写入或清空。
判定数据来自 `services/state_machine.py` 的状态集合与工作台查询口径，不另行发明规则。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.enums import (
    FactStatus,
    KnowledgeCandidateStatus,
    KnowledgeParseStatus,
    PublishTaskStatus,
    TaskStatus,
)
from app.services.state_machine import (
    ensure_alert_event_transition,  # noqa: F401  (预留：预警不新增列，此处仅保持导入一致)
    ensure_knowledge_candidate_transition,
    ensure_knowledge_parse_transition,
    ensure_publish_transition,
    ensure_fact_transition,
    ensure_task_transition,
)

# 各实体的待办集合：与 workbench_todos 的过滤条件逐一对应
PUBLISH_TODO = frozenset({PublishTaskStatus.PENDING, PublishTaskStatus.NEEDS_REVIEW})
MONITORING_TODO = frozenset({TaskStatus.FAILED, TaskStatus.UNCERTAIN})
FACT_TODO = frozenset({FactStatus.DRAFT, FactStatus.PENDING_REVIEW})
KNOWLEDGE_PARSE_TODO = frozenset(
    {
        KnowledgeParseStatus.PENDING,
        KnowledgeParseStatus.PARSING,
        KnowledgeParseStatus.FAILED,
        KnowledgeParseStatus.UNSUPPORTED,
    }
)
KNOWLEDGE_CANDIDATE_TODO = frozenset({KnowledgeCandidateStatus.SUGGESTED})


def fact_has_source(fact) -> bool:
    """来源是否存在。

    与查询侧 `coalesce(nullif(source_document, ''), nullif(source_url, ''))` 逐字对齐：
    只把 None 与空字符串视为缺失，纯空白仍算"有来源"，避免判定分叉（R-01 v2.1 §2.1）。
    """
    return bool(fact.source_document) or bool(fact.source_url)


def fact_in_todo(fact) -> bool:
    """事实审批组的组合成员资格：状态条件或来源缺失条件，二者取并集。"""
    return fact.approval_status in FACT_TODO or not fact_has_source(fact)


def sync_cycle(obj, *, old_in: bool, new_in: bool, now: datetime | None = None) -> None:
    """四象限写入：只在跨越集合边界时改动 entered_todo_at。

    - 集合内 → 集合内：不动（普通更新、重试、内部迁移）
    - 集合外 → 集合内：写入当前时间
    - 集合内 → 集合外：置 NULL
    - 集合外 → 集合外：不动
    """
    if old_in == new_in:
        return
    obj.entered_todo_at = (now or datetime.now(timezone.utc)) if new_in else None


def apply_publish_status(task, target: PublishTaskStatus, *, now: datetime | None = None):
    old = task.status
    task.status = ensure_publish_transition(old, target)
    sync_cycle(task, old_in=old in PUBLISH_TODO, new_in=task.status in PUBLISH_TODO, now=now)
    return task.status


def apply_task_status(task, target: TaskStatus, *, now: datetime | None = None):
    old = task.status
    task.status = ensure_task_transition(old, target)
    sync_cycle(task, old_in=old in MONITORING_TODO, new_in=task.status in MONITORING_TODO, now=now)
    return task.status


def apply_fact_status(fact, target: FactStatus, *, now: datetime | None = None):
    old_in = fact_in_todo(fact)
    fact.approval_status = ensure_fact_transition(fact.approval_status, target)
    sync_cycle(fact, old_in=old_in, new_in=fact_in_todo(fact), now=now)
    return fact.approval_status


def apply_parse_status(document, target: KnowledgeParseStatus, *, now: datetime | None = None):
    old = document.parse_status
    document.parse_status = ensure_knowledge_parse_transition(old, target)
    sync_cycle(
        document,
        old_in=old in KNOWLEDGE_PARSE_TODO,
        new_in=document.parse_status in KNOWLEDGE_PARSE_TODO,
        now=now,
    )
    return document.parse_status


def apply_candidate_status(
    candidate, target: KnowledgeCandidateStatus, *, now: datetime | None = None
):
    old = candidate.status
    candidate.status = ensure_knowledge_candidate_transition(old, target)
    sync_cycle(
        candidate,
        old_in=old in KNOWLEDGE_CANDIDATE_TODO,
        new_in=candidate.status in KNOWLEDGE_CANDIDATE_TODO,
        now=now,
    )
    return candidate.status


__all__ = [
    "PUBLISH_TODO",
    "MONITORING_TODO",
    "FACT_TODO",
    "KNOWLEDGE_PARSE_TODO",
    "KNOWLEDGE_CANDIDATE_TODO",
    "fact_has_source",
    "fact_in_todo",
    "sync_cycle",
    "apply_publish_status",
    "apply_task_status",
    "apply_fact_status",
    "apply_parse_status",
    "apply_candidate_status",
]

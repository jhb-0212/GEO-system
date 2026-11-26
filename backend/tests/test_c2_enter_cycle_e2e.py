"""C2-3：`entered_todo_at` 写入时机与业务日界、DST 的联动。

C2-1 验证"窗口算得对"，C2-2 验证"接口按窗口过滤"，本文件验证第三件事：
**对象在什么时刻被写进 `entered_todo_at`，决定它落在哪个业务自然日**，
以及集合内部迁移不得跨日刷新该值（ADR-01 的四象限）。

默认跳过；`GEO_C2_DST_MATRIX=1` 打开。
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Fact
from app.models.enums import FactStatus, FactType
from app.services.time_windows import resolve_timezone
from app.services.todo_clock import apply_fact_status
from app.services.workbench_todos import todo_snapshot

RUN_MATRIX = os.environ.get("GEO_C2_DST_MATRIX") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_MATRIX,
    reason="C2 真实数据库矩阵；设置 GEO_C2_DST_MATRIX=1 后运行",
)

SHANGHAI_DAY_START = datetime(2026, 11, 25, 16, 0, tzinfo=UTC)
SHANGHAI_DAY_END = datetime(2026, 11, 26, 16, 0, tzinfo=UTC)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _project(db, zone: str):
    from sqlalchemy import select

    from app.models import Project
    from app.models.industry import Organization

    suffix = uuid.uuid4().hex[:6]
    org = db.scalar(select(Organization).where(Organization.code == "default-client"))
    if org is None:
        org = Organization(code="default-client", name="默认客户", status="active", branding={})
        db.add(org)
        db.flush()
    project = Project(
        code=f"c2cycle-{suffix}",
        name=f"C2 周期-{zone}",
        status="active",
        timezone=zone,
        organization_id=org.id,
    )
    db.add(project)
    db.flush()
    return project


def _fact(db, project, status: FactStatus) -> Fact:
    fact = Fact(
        project_id=project.id,
        fact_type=FactType.BASE_ADDRESS,
        fact_key=f"cycle-{uuid.uuid4().hex[:8]}",
        fact_value="C2 写入时机样本",
        approval_status=status,
        source_url="https://example.com/c2-cycle",
    )
    db.add(fact)
    db.flush()
    return fact


def _facts_today(db, project, now: datetime) -> tuple[int, list[datetime]]:
    snapshot = todo_snapshot(db, project.id, range_value="today", limit=50, now=now)
    group = next(g for g in snapshot["groups"] if g["key"] == "facts")
    return group["counts"]["today"], [datetime.fromisoformat(item["at"]) for item in group["items"]]


def test_enter_before_local_midnight_counts_today(db) -> None:
    project = _project(db, "Asia/Shanghai")
    fact = _fact(db, project, FactStatus.APPROVED)  # 集合外

    last_second = SHANGHAI_DAY_END - timedelta(seconds=1)
    apply_fact_status(fact, FactStatus.DRAFT, now=last_second)
    db.flush()

    assert fact.entered_todo_at == last_second
    count, ats = _facts_today(db, project, now=SHANGHAI_DAY_END - timedelta(hours=4))
    assert count == 1 and ats == [last_second]


def test_enter_at_local_midnight_lands_on_next_day(db) -> None:
    """同一行数据：日界前后两个“现在”分别看到 / 看不到它。"""
    project = _project(db, "Asia/Shanghai")
    fact = _fact(db, project, FactStatus.APPROVED)

    apply_fact_status(fact, FactStatus.DRAFT, now=SHANGHAI_DAY_END)
    db.flush()
    assert fact.entered_todo_at == SHANGHAI_DAY_END

    before = _facts_today(db, project, now=SHANGHAI_DAY_END - timedelta(seconds=1))
    after = _facts_today(db, project, now=SHANGHAI_DAY_END + timedelta(hours=8))
    assert before[0] == 0, "日界前 1 秒的“今天”不应包含 00:00 进入的对象"
    assert after[0] == 1 and after[1] == [SHANGHAI_DAY_END]


def test_dst_spring_entering_records_real_instant(db) -> None:
    """纽约春季跳变后进入：记录的是真实瞬时，本地展示为 03:xx，且落在当日窗口内。"""
    project = _project(db, "America/New_York")
    fact = _fact(db, project, FactStatus.APPROVED)

    entered = _dt("2026-03-08T07:00:00+00:00")  # 本地 03:00 EDT
    apply_fact_status(fact, FactStatus.DRAFT, now=entered)
    db.flush()

    assert fact.entered_todo_at == entered
    assert entered.astimezone(resolve_timezone("America/New_York")).hour == 3
    count, ats = _facts_today(db, project, now=_dt("2026-03-08T16:00:00+00:00"))
    assert count == 1 and ats == [entered]


def test_in_set_transition_does_not_refresh_across_midnight(db) -> None:
    """DRAFT → PENDING_REVIEW 仍在待办集合内：跨过日界也不得刷新进入时间。"""
    project = _project(db, "Asia/Shanghai")
    fact = _fact(db, project, FactStatus.APPROVED)

    first_enter = SHANGHAI_DAY_END - timedelta(hours=1)
    apply_fact_status(fact, FactStatus.DRAFT, now=first_enter)
    db.flush()
    assert fact.entered_todo_at == first_enter

    apply_fact_status(fact, FactStatus.PENDING_REVIEW, now=SHANGHAI_DAY_END + timedelta(minutes=30))
    db.flush()
    assert fact.entered_todo_at == first_enter, "集合内部迁移刷新了进入时间，会破坏跨日归属"

    next_day = _facts_today(db, project, now=SHANGHAI_DAY_END + timedelta(hours=1))
    assert next_day[0] == 0, "昨日进入的对象不应被算进今天的待办"
    snapshot_week = todo_snapshot(
        db, project.id, range_value="week", limit=50, now=SHANGHAI_DAY_END + timedelta(hours=1)
    )
    week_group = next(g for g in snapshot_week["groups"] if g["key"] == "facts")
    assert week_group["counts"]["week"] == 1


def test_exit_then_reenter_gets_fresh_timestamp(db) -> None:
    project = _project(db, "Asia/Shanghai")
    fact = _fact(db, project, FactStatus.APPROVED)

    first = SHANGHAI_DAY_END - timedelta(hours=1)
    apply_fact_status(fact, FactStatus.DRAFT, now=first)
    apply_fact_status(fact, FactStatus.PENDING_REVIEW, now=first + timedelta(minutes=5))
    apply_fact_status(fact, FactStatus.APPROVED, now=first + timedelta(minutes=10))  # 退出集合
    db.flush()
    assert fact.entered_todo_at is None

    second = SHANGHAI_DAY_END + timedelta(hours=2)
    apply_fact_status(fact, FactStatus.DRAFT, now=second)  # 再次进入
    db.flush()
    assert fact.entered_todo_at == second

    count, ats = _facts_today(db, project, now=SHANGHAI_DAY_END + timedelta(hours=3))
    assert count == 1 and ats == [second], "再次进入应记录新的进入时间"

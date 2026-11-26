"""C2 补证：午夜本身重复/不存在、整日被跳过时的日界选择。

背景：现有 DST 矩阵验证的是“白天跳变”（纽约 02:00→03:00）与“01:30 重复”，
但没有直接验证本地 00:00 本身是重复时刻或不存在时刻时，`_local_midnight_utc()`
的 `fold=0` 与“取当日首个真实瞬间”规则。本文件补这三类直接证据。

选例依据（都来自 tzdata 实测，不是照抄建议值）：
- 午夜重复：`Atlantic/Azores 2026-10-25`（01:00 回拨到 00:00，00:00 出现两次）；
  反例说明：`America/Havana 2026-11-01` 午夜并不重复（古巴在 01:00 回拨，
  00:00 只出现一次），不能用来测 fold。
- 午夜不存在：`America/Sao_Paulo 2018-11-04`（00:00 直接跳到 01:00）。
- 整日不存在：`Pacific/Apia 2011-12-30`（跨国际日期变更线跳日）。

默认跳过；`GEO_C2_DST_MATRIX=1` 打开，与 C2 矩阵同一个 CI 步骤。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.models import Fact, Project
from app.models.enums import FactStatus, FactType
from app.services.time_windows import (
    ProjectTimezoneInvalid,
    local_day_start_utc,
    resolve_timezone,
)
from app.services.workbench_todos import todo_snapshot

RUN_MATRIX = __import__("os").environ.get("GEO_C2_DST_MATRIX") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_MATRIX,
    reason="C2 真实数据库矩阵；设置 GEO_C2_DST_MATRIX=1 后运行",
)


def _midnight(zone: str, day: date, fold: int) -> datetime:
    return datetime.combine(day, time.min, tzinfo=resolve_timezone(zone)).replace(fold=fold)


def _project(db, name: str, zone: str) -> Project:
    project = Project(code=name, name=name, timezone=zone)
    db.add(project)
    db.flush()
    return project


def _add_fact(db, project: Project, key: str, at: datetime) -> Fact:
    fact = Fact(
        project_id=project.id,
        fact_type=FactType.BASE_ADDRESS,
        fact_key=f"{key}-{uuid.uuid4().hex[:8]}",
        fact_value="C2 午夜边界样本",
        approval_status=FactStatus.DRAFT,
        source_url="https://example.com/c2-midnight",
        entered_todo_at=at,
    )
    db.add(fact)
    db.flush()
    return fact


def _fact_group(payload: dict) -> dict:
    return next(group for group in payload["groups"] if group["key"] == "facts")


def test_repeated_midnight_takes_fold_zero() -> None:
    """Azores 2026-10-25：本地 00:00 出现两次，日界取 fold=0（较早的 00:00Z）。"""
    zone, day = "Atlantic/Azores", date(2026, 10, 25)
    first, second = _midnight(zone, day, 0).astimezone(UTC), _midnight(zone, day, 1).astimezone(UTC)

    # 先证明这个用例确实有歧义，否则断言恒真
    assert first != second
    assert second - first == timedelta(hours=1)
    assert first.astimezone(resolve_timezone(zone)).time() == time(0, 0)
    assert second.astimezone(resolve_timezone(zone)).time() == time(0, 0)

    assert local_day_start_utc(resolve_timezone(zone), day) == datetime(2026, 10, 25, 0, 0, tzinfo=UTC)


def test_nonexistent_midnight_uses_first_valid_instant() -> None:
    """São Paulo 2018-11-04：本地 00:00 不存在，日界取当天 01:00（03:00Z）。"""
    zone, day = "America/Sao_Paulo", date(2018, 11, 4)
    zoneinfo = resolve_timezone(zone)

    start = local_day_start_utc(zoneinfo, day)
    assert start == datetime(2018, 11, 4, 3, 0, tzinfo=UTC)
    # 返回的是“当日第一个真实瞬间”，不是假想的 00:00
    assert start.astimezone(zoneinfo).time() == time(1, 0)
    # 同一个日期的两种 fold 解释不等价，说明午夜确实缺失
    assert _midnight(zone, day, 0).astimezone(UTC) != _midnight(zone, day, 1).astimezone(UTC)


def test_skipped_day_raises_instead_of_silent_drift() -> None:
    """Apia 2011-12-30 整日被跳过：必须报错，不能静默返回次日边界。"""
    with pytest.raises(ProjectTimezoneInvalid):
        local_day_start_utc(resolve_timezone("Pacific/Apia"), date(2011, 12, 30))


def test_repeated_midnight_window_is_half_open_in_database(db) -> None:
    """真实库：Azores 10-25 的窗口从 fold=0 的 00:00Z 起，00:00Z 计入、前 1 秒排除。"""
    zone = "Atlantic/Azores"
    project = _project(db, f"c2-midnight-{uuid.uuid4().hex[:6]}", zone)
    start = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
    # 回拨后 Azores 变为 UTC-1，所以次日零点落在 01:00Z；这一日本身是 25 小时
    end = datetime(2026, 10, 26, 1, 0, tzinfo=UTC)

    _add_fact(db, project, "before", start - timedelta(seconds=1))
    _add_fact(db, project, "start", start)
    _add_fact(db, project, "before-end", end - timedelta(seconds=1))
    _add_fact(db, project, "end", end)

    snapshot = todo_snapshot(db, project.id, range_value="today", limit=50, now=start + timedelta(hours=12))
    assert snapshot["window"] == {
        "start": "2026-10-25T00:00:00+00:00",
        "end": "2026-10-26T01:00:00+00:00",
    }
    assert _fact_group(snapshot)["counts"]["today"] == 2

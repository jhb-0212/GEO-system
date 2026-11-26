"""C2：DST 与自然日边界的真实数据库矩阵。

默认跳过；用 `GEO_C2_DST_MATRIX=1` 打开（CI 独立步骤显式打开，避免日常全量
测试变慢）。

验证分层：
1. 计算层：`ProjectCalendar.window()` 产出的 UTC 边界必须等于**硬编码的期望值**
   （期望值由独立的时区数据库提供，不由被测算法自己算出来，避免自证）。
2. 数据库层：`todo_snapshot(..., range="today"/"week")` 的真实 PostgreSQL 查询
   必须遵守 `[start, end)`：`start` 前 1 秒被排除，`start` 计入，`end` 前一秒计入，
   `end` 排除。
3. DST 层：跳过的本地时间（春季）与重复的本地时间（秋季）都能被正确归入同一个
   业务自然日，且该日窗口长度是 23h / 25h。
4. 归属层：同一个 UTC 时刻在不同业务时区的自然日归属不同。
5. 变更层：改项目时区后窗口随之前后移动。
6. 负向对照：把窗口整体平移 1 小时，计数必须变化——证明错误窗口会被捕获。
7. 静态扫描：前端不再出现 `86_400_000` / 浏览器本地时区参与业务窗口计算。
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import Fact, Project
from app.models.enums import FactStatus, FactType
from app.services.time_windows import project_calendar, resolve_timezone
from app.services.workbench_todos import todo_snapshot

RUN_MATRIX = os.environ.get("GEO_C2_DST_MATRIX") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_MATRIX,
    reason="C2 真实数据库矩阵；设置 GEO_C2_DST_MATRIX=1 后运行",
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# 期望值来源：独立 IANA tzdata 推导后人工核对并硬编码（不由被测函数生成）。
# (业务时区, 本地自然日) -> (start ISO, end ISO, 窗口小时数)
DAY_WINDOWS: dict[tuple[str, str], tuple[str, str, float]] = {
    ("UTC", "2026-11-26"): ("2026-11-26T00:00:00+00:00", "2026-11-27T00:00:00+00:00", 24.0),
    ("Asia/Shanghai", "2026-11-26"): ("2026-11-25T16:00:00+00:00", "2026-11-26T16:00:00+00:00", 24.0),
    # 月末边界
    ("Asia/Shanghai", "2026-11-30"): ("2026-11-29T16:00:00+00:00", "2026-11-30T16:00:00+00:00", 24.0),
    # 年末边界
    ("Asia/Shanghai", "2026-12-31"): ("2026-12-30T16:00:00+00:00", "2026-12-31T16:00:00+00:00", 24.0),
    ("America/New_York", "2026-11-26"): ("2026-11-26T05:00:00+00:00", "2026-11-27T05:00:00+00:00", 24.0),
    # DST 开始：本地 2026-03-08 02:00 → 03:00，该日 23 小时
    ("America/New_York", "2026-03-08"): ("2026-03-08T05:00:00+00:00", "2026-03-09T04:00:00+00:00", 23.0),
    # DST 结束：本地 2026-11-01 02:00 → 01:00，该日 25 小时
    ("America/New_York", "2026-11-01"): ("2026-11-01T04:00:00+00:00", "2026-11-02T05:00:00+00:00", 25.0),
    ("Europe/Berlin", "2026-11-26"): ("2026-11-25T23:00:00+00:00", "2026-11-26T23:00:00+00:00", 24.0),
    ("Europe/Berlin", "2026-03-29"): ("2026-03-28T23:00:00+00:00", "2026-03-29T22:00:00+00:00", 23.0),
    ("Europe/Berlin", "2026-10-25"): ("2026-10-24T22:00:00+00:00", "2026-10-25T23:00:00+00:00", 25.0),
    ("Asia/Tokyo", "2026-11-26"): ("2026-11-25T15:00:00+00:00", "2026-11-26T15:00:00+00:00", 24.0),
    # 月末 / 年末：其余时区（补齐矩阵为 5 时区 × 3 个日历边界）
    ("UTC", "2026-11-30"): ("2026-11-30T00:00:00+00:00", "2026-12-01T00:00:00+00:00", 24.0),
    ("UTC", "2026-12-31"): ("2026-12-31T00:00:00+00:00", "2027-01-01T00:00:00+00:00", 24.0),
    ("America/New_York", "2026-11-30"): ("2026-11-30T05:00:00+00:00", "2026-12-01T05:00:00+00:00", 24.0),
    ("America/New_York", "2026-12-31"): ("2026-12-31T05:00:00+00:00", "2027-01-01T05:00:00+00:00", 24.0),
    ("Europe/Berlin", "2026-11-30"): ("2026-11-29T23:00:00+00:00", "2026-11-30T23:00:00+00:00", 24.0),
    ("Europe/Berlin", "2026-12-31"): ("2026-12-30T23:00:00+00:00", "2026-12-31T23:00:00+00:00", 24.0),
    ("Asia/Tokyo", "2026-11-30"): ("2026-11-29T15:00:00+00:00", "2026-11-30T15:00:00+00:00", 24.0),
    ("Asia/Tokyo", "2026-12-31"): ("2026-12-30T15:00:00+00:00", "2026-12-31T15:00:00+00:00", 24.0),
}


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _project(db, code: str, zone: str) -> Project:
    from app.models.industry import Organization

    org = db.scalar(select(Organization).where(Organization.code == "default-client"))
    if org is None:
        org = Organization(code="default-client", name="默认客户", status="active", branding={})
        db.add(org)
        db.flush()
    project = Project(
        code=code,
        name=f"C2-{zone}-{code}",
        status="active",
        timezone=zone,
        organization_id=org.id,
    )
    db.add(project)
    db.flush()
    return project


def _add_fact(db, project: Project, key: str, at: datetime | None) -> Fact:
    fact = Fact(
        project_id=project.id,
        fact_type=FactType.BASE_ADDRESS,
        fact_key=f"{key}-{uuid.uuid4().hex[:8]}",
        fact_value="C2 边界样本",
        approval_status=FactStatus.DRAFT,
        source_url="https://example.com/c2",
        entered_todo_at=at,
    )
    db.add(fact)
    db.flush()
    return fact


def _fact_group(snapshot: dict) -> dict:
    return next(group for group in snapshot["groups"] if group["key"] == "facts")


@pytest.mark.parametrize(("zone", "local_day"), sorted(DAY_WINDOWS))
def test_calendar_window_matches_hardcoded_utc(zone: str, local_day: str) -> None:
    expected_start, expected_end, expected_hours = DAY_WINDOWS[(zone, local_day)]
    start, end = _dt(expected_start), _dt(expected_end)

    class _P:
        timezone = zone

    calendar = project_calendar(_P(), now=start + (end - start) / 2)
    window = calendar.window("today")

    assert window.start == start, f"{zone} {local_day} 日界起点不符"
    assert window.end == end, f"{zone} {local_day} 日界终点不符"
    assert (window.end - window.start).total_seconds() / 3600 == expected_hours
    assert calendar.local_today == date.fromisoformat(local_day)


@pytest.mark.parametrize(("zone", "local_day"), sorted(DAY_WINDOWS))
def test_realdb_todo_window_is_half_open(db, zone: str, local_day: str) -> None:
    expected_start, expected_end, _ = DAY_WINDOWS[(zone, local_day)]
    start, end = _dt(expected_start), _dt(expected_end)

    project = _project(db, f"c2-{uuid.uuid4().hex[:6]}", zone)
    _add_fact(db, project, "before", start - timedelta(seconds=1))
    _add_fact(db, project, "at-start", start)
    _add_fact(db, project, "before-end", end - timedelta(seconds=1))
    _add_fact(db, project, "at-end", end)

    snapshot = todo_snapshot(db, project.id, range_value="today", limit=50, now=start + (end - start) / 2)
    facts = _fact_group(snapshot)

    assert snapshot["business_timezone"] == zone
    assert snapshot["window"] == {"start": expected_start, "end": expected_end}
    assert facts["counts"]["today"] == 2, "左闭右开被破坏：应为 [start, end) 恰好 2 条"
    # PostgreSQL 返回的 timestamptz 会按会话时区渲染（本机为 +08:00），
    # 因此必须按“瞬时”比较，不能直接比 ISO 字符串。
    ats = sorted(datetime.fromisoformat(item["at"]) for item in facts["items"])
    assert ats == sorted([start, end - timedelta(seconds=1)])


def test_dst_skipped_local_time_lands_in_same_day(db) -> None:
    """纽约春季 02:00–02:59 不存在：跳变前后两个 UTC 时刻仍属同一业务自然日。"""
    zone, local_day = "America/New_York", "2026-03-08"
    expected_start, expected_end, _ = DAY_WINDOWS[(zone, local_day)]
    start, end = _dt(expected_start), _dt(expected_end)

    project = _project(db, f"c2-{uuid.uuid4().hex[:6]}", zone)
    before_jump = datetime(2026, 3, 8, 6, 59, 59, tzinfo=UTC)   # 01:59:59 EST
    at_jump = datetime(2026, 3, 8, 7, 0, 0, tzinfo=UTC)         # 03:00:00 EDT
    _add_fact(db, project, "pre-jump", before_jump)
    _add_fact(db, project, "post-jump", at_jump)

    ny = resolve_timezone(zone)
    assert before_jump.astimezone(ny).hour == 1
    assert at_jump.astimezone(ny).hour == 3, "跳变后应直接进入 03 点，02 点不存在"

    snapshot = todo_snapshot(db, project.id, range_value="today", limit=50, now=start + (end - start) / 2)
    assert _fact_group(snapshot)["counts"]["today"] == 2


def test_dst_repeated_local_time_stays_distinct(db) -> None:
    """纽约秋季 01:00–01:59 出现两次：两个不同 UTC 时刻都要计入同一自然日。"""
    zone, local_day = "America/New_York", "2026-11-01"
    expected_start, expected_end, _ = DAY_WINDOWS[(zone, local_day)]
    start, end = _dt(expected_start), _dt(expected_end)

    project = _project(db, f"c2-{uuid.uuid4().hex[:6]}", zone)
    first = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)   # 01:30 EDT
    second = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)  # 01:30 EST（重复的本地时间）
    _add_fact(db, project, "first", first)
    _add_fact(db, project, "second", second)

    ny = resolve_timezone(zone)
    assert first.astimezone(ny).hour == second.astimezone(ny).hour == 1
    assert first != second

    snapshot = todo_snapshot(db, project.id, range_value="today", limit=50, now=start + (end - start) / 2)
    assert _fact_group(snapshot)["counts"]["today"] == 2


def test_same_instant_belongs_to_different_local_days(db) -> None:
    """同一 UTC 时刻：上海属 11-27 凌晨（不计入 11-26），UTC 属 11-26 白天（计入）。"""
    instant = datetime(2026, 11, 26, 16, 30, tzinfo=UTC)

    shanghai = _project(db, f"c2-{uuid.uuid4().hex[:6]}", "Asia/Shanghai")
    utc_project = _project(db, f"c2-{uuid.uuid4().hex[:6]}", "UTC")
    _add_fact(db, shanghai, "same", instant)
    _add_fact(db, utc_project, "same", instant)

    snap_sh = todo_snapshot(
        db, shanghai.id, range_value="today", limit=50, now=datetime(2026, 11, 26, 4, 0, tzinfo=UTC)
    )
    snap_utc = todo_snapshot(
        db, utc_project.id, range_value="today", limit=50, now=datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
    )

    assert snap_sh["window"] == {"start": "2026-11-25T16:00:00+00:00", "end": "2026-11-26T16:00:00+00:00"}
    assert snap_utc["window"] == {"start": "2026-11-26T00:00:00+00:00", "end": "2026-11-27T00:00:00+00:00"}
    assert _fact_group(snap_sh)["counts"]["today"] == 0
    assert _fact_group(snap_utc)["counts"]["today"] == 1


def test_week_window_starts_monday_and_is_half_open(db) -> None:
    """上海：周三所在的自然周为 [周一 00:00, 下周一 00:00)。"""
    zone = "Asia/Shanghai"
    project = _project(db, f"c2-{uuid.uuid4().hex[:6]}", zone)
    now = datetime(2026, 11, 25, 4, 0, tzinfo=UTC)  # 本地周三 12:00

    sunday_last_second = datetime(2026, 11, 22, 15, 59, 59, tzinfo=UTC)  # 周日 23:59:59
    monday_first = datetime(2026, 11, 22, 16, 0, 0, tzinfo=UTC)          # 周一 00:00
    next_sunday_last_second = datetime(2026, 11, 29, 15, 59, 59, tzinfo=UTC)
    next_monday = datetime(2026, 11, 29, 16, 0, 0, tzinfo=UTC)

    _add_fact(db, project, "prev-sun", sunday_last_second)
    _add_fact(db, project, "mon", monday_first)
    _add_fact(db, project, "sun-end", next_sunday_last_second)
    _add_fact(db, project, "next-mon", next_monday)

    snapshot = todo_snapshot(db, project.id, range_value="week", limit=50, now=now)
    assert snapshot["window"] == {"start": "2026-11-22T16:00:00+00:00", "end": "2026-11-29T16:00:00+00:00"}
    assert _fact_group(snapshot)["counts"]["week"] == 2


def test_timezone_change_shifts_window_and_counts(db) -> None:
    """项目时区改动后，窗口整体移动到对应偏移，计数随之变化。"""
    project = _project(db, f"c2-{uuid.uuid4().hex[:6]}", "Asia/Shanghai")
    now = datetime(2026, 11, 26, 4, 0, tzinfo=UTC)  # 上海 12:00 / 东京 13:00
    instant = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)  # 上海 11-25 23:30；东京 11-26 00:30
    _add_fact(db, project, "edge", instant)

    before = todo_snapshot(db, project.id, range_value="today", limit=50, now=now)
    assert before["window"]["start"] == "2026-11-25T16:00:00+00:00"
    assert _fact_group(before)["counts"]["today"] == 0

    project.timezone = "Asia/Tokyo"
    db.flush()

    after = todo_snapshot(db, project.id, range_value="today", limit=50, now=now)
    assert after["business_timezone"] == "Asia/Tokyo"
    assert after["window"]["start"] == "2026-11-25T15:00:00+00:00"
    assert _fact_group(after)["counts"]["today"] == 1


def test_shifted_window_would_be_caught(db) -> None:
    """负向对照：窗口整体平移 1 小时后计数必须变化，证明错误窗口可被捕获。"""
    zone, local_day = "Asia/Shanghai", "2026-11-26"
    expected_start, expected_end, _ = DAY_WINDOWS[(zone, local_day)]
    start, end = _dt(expected_start), _dt(expected_end)

    project = _project(db, f"c2-{uuid.uuid4().hex[:6]}", zone)
    inside_but_near_edge = start + timedelta(minutes=30)
    _add_fact(db, project, "edge", inside_but_near_edge)

    correct = todo_snapshot(db, project.id, range_value="today", limit=50, now=start + (end - start) / 2)
    assert _fact_group(correct)["counts"]["today"] == 1

    shifted_start, shifted_end = start + timedelta(hours=1), end + timedelta(hours=1)
    stmt = (
        select(func.count())
        .select_from(Fact)
        .where(
            Fact.project_id == project.id,
            Fact.approval_status.in_([FactStatus.DRAFT, FactStatus.PENDING_REVIEW]),
            Fact.entered_todo_at >= shifted_start,
            Fact.entered_todo_at < shifted_end,
        )
    )
    assert db.scalar(stmt) == 0, "平移 1 小时的错误窗口仍命中，说明对照用例失去判别力"


def test_frontend_has_no_local_calendar_math() -> None:
    """前端不得自行算自然日：禁止固定毫秒日长与浏览器本地时区偏移。"""
    roots = [
        REPO_ROOT / "frontend" / "components" / "workbench",
        REPO_ROOT / "frontend" / "app" / "internal" / "workbench",
    ]
    offenders: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            text = path.read_text(encoding="utf-8")
            for token in ("86_400_000", "86400000", "getTimezoneOffset"):
                if token in text:
                    offenders.append(f"{path.relative_to(REPO_ROOT)} 含 {token}")
    assert not offenders, "前端重新引入本地日界计算：" + "；".join(offenders)

    # 旧偏移参数只允许出现在兼容转发路由里
    allowed = REPO_ROOT / "frontend" / "app" / "internal" / "workbench" / "todos" / "route.ts"
    others = [
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "frontend").rglob("*.ts*")
        if "tz_offset_minutes" in path.read_text(encoding="utf-8", errors="ignore")
        and path != allowed
    ]
    assert not others, "tz_offset_minutes 出现在兼容转发路由之外：" + "；".join(others)

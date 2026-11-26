"""项目业务日历：唯一窗口事实源、DST、日界与非法时区。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services.time_windows import (
    ProjectTimezoneInvalid,
    calendar_window,
    local_day_start_utc,
    project_calendar,
)


def _project(tz: str = "Asia/Shanghai"):
    return SimpleNamespace(timezone=tz)


def test_today_window_uses_project_timezone_not_caller():
    moment = datetime(2026, 11, 25, 3, 0, tzinfo=UTC)  # 纽约 11-24 22:00，上海 11-25 11:00
    sh = project_calendar(_project("Asia/Shanghai"), now=moment)
    ny = project_calendar(_project("America/New_York"), now=moment)
    assert sh.local_today.isoformat() == "2026-11-25"
    assert ny.local_today.isoformat() == "2026-11-24"
    sh_today = sh.window("today")
    ny_today = ny.window("today")
    assert sh_today.start != ny_today.start
    assert sh_today.end - sh_today.start == timedelta(hours=24)
    assert ny_today.end - ny_today.start == timedelta(hours=24)


def test_week_starts_monday_and_is_left_closed_right_open():
    moment = datetime(2026, 11, 26, 5, 47, tzinfo=UTC)  # 周四
    calendar = project_calendar(_project(), now=moment)
    week = calendar.window("week")
    assert calendar.week_start_date.isoformat() == "2026-11-23"
    assert week.start == datetime(2026, 11, 22, 16, 0, tzinfo=UTC)  # 上海 11-23 00:00
    assert week.end == datetime(2026, 11, 29, 16, 0, tzinfo=UTC)  # 上海 11-30 00:00
    assert week.end - week.start == timedelta(days=7)


def test_dst_fall_back_day_is_25_hours():
    calendar = project_calendar(_project("America/New_York"), now=datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    today = calendar.window("today")  # 纽约 11-01 08:00
    assert today.end - today.start == timedelta(hours=25)


def test_dst_spring_forward_day_is_23_hours():
    calendar = project_calendar(_project("America/New_York"), now=datetime(2026, 3, 8, 12, 0, tzinfo=UTC))
    today = calendar.window("today")  # 纽约 03-08 08:00
    assert today.end - today.start == timedelta(hours=23)


def test_midnight_that_does_not_exist_uses_first_valid_instant():
    # 2018-11-04 巴西夏令时开始，00:00 直接跳到 01:00。
    zone = ZoneInfo("America/Sao_Paulo")
    start = local_day_start_utc(zone, datetime(2018, 11, 4).date())
    assert start.astimezone(zone).date().isoformat() == "2018-11-04"
    assert start.astimezone(zone).hour == 1


def test_calendar_window_projection_keeps_trailing_days_semantics():
    moment = datetime(2026, 11, 25, 3, 0, tzinfo=UTC)
    project = _project("America/New_York")
    start_date, end_date, start_at = calendar_window(project, 30, now=moment)
    assert end_date.isoformat() == "2026-11-24"
    assert start_date.isoformat() == "2026-10-26"
    assert start_at == datetime(2026, 10, 26, 4, 0, tzinfo=UTC)  # 纽约 10-26 00:00 EDT


def test_invalid_timezone_raises_instead_of_falling_back():
    for name in ("Mars/Olympus", "", "   "):
        with pytest.raises(ProjectTimezoneInvalid):
            project_calendar(_project(name), now=datetime(2026, 11, 25, tzinfo=UTC))


def test_single_now_is_fixed_for_all_windows():
    moment = datetime(2026, 11, 26, 15, 59, 59, tzinfo=UTC)  # 上海 23:59:59
    calendar = project_calendar(_project(), now=moment)
    assert calendar.now == moment
    today = calendar.window("today")
    assert today.start.astimezone(calendar.zone).date() == calendar.local_today

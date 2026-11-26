"""月报/线索项目级日期窗口：右开边界、DST 与非法时区。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services.reports import month_window, resolve_date_window
from app.services.time_windows import ProjectTimezoneInvalid


def _project(tz: str = "Asia/Shanghai"):
    return SimpleNamespace(timezone=tz)


def test_report_date_window_is_left_closed_right_open():
    start_at, end_at = resolve_date_window(
        _project("America/New_York"), datetime(2026, 3, 7).date(), datetime(2026, 3, 8).date()
    )
    assert start_at == datetime(2026, 3, 7, 5, 0, tzinfo=UTC)  # 纽约 03-07 00:00 EST
    # 03-08 是 DST 开始日，次日零点为 03-09 00:00 EDT。
    assert end_at == datetime(2026, 3, 9, 4, 0, tzinfo=UTC)


def test_report_month_window_spans_dst_and_keeps_end_exclusive():
    start_at, end_at, label = month_window(_project("America/New_York"), "2026-03")
    assert label == "2026-03"
    assert start_at == datetime(2026, 3, 1, 5, 0, tzinfo=UTC)
    assert end_at == datetime(2026, 4, 1, 4, 0, tzinfo=UTC)
    assert start_at.astimezone(ZoneInfo("America/New_York")).date().isoformat() == "2026-03-01"
    assert end_at.astimezone(ZoneInfo("America/New_York")).date().isoformat() == "2026-04-01"


def test_report_windows_reject_invalid_project_timezone():
    with pytest.raises(ProjectTimezoneInvalid):
        resolve_date_window(_project("Mars/Olympus"), datetime(2026, 3, 1).date(), None)
    with pytest.raises(ProjectTimezoneInvalid):
        month_window(_project("Mars/Olympus"), "2026-03")

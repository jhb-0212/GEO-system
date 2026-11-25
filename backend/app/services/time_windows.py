"""业务统计窗口：按项目时区取自然日，时间戳仍统一按 UTC 查询。"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import Project

DEFAULT_TIMEZONE = "Asia/Shanghai"


def resolve_timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def project_timezone(project) -> ZoneInfo:
    return resolve_timezone(getattr(project, "timezone", None))


def local_today(zone: ZoneInfo, *, now: datetime | None = None) -> date:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(zone).date()


def calendar_window(project, days: int, *, now: datetime | None = None) -> tuple[date, date, datetime]:
    """返回 (起始日, 结束日, 起始 UTC 时刻)，两端都包含自然日。"""
    zone = project_timezone(project)
    end_date = local_today(zone, now=now)
    start_date = end_date - timedelta(days=max(days, 1) - 1)
    start_at = datetime.combine(start_date, time.min, tzinfo=zone).astimezone(UTC)
    return start_date, end_date, start_at


def project_calendar_window(
    db, project_id, days: int, *, now: datetime | None = None
) -> tuple[date, date, datetime]:
    return calendar_window(db.get(Project, project_id), days, now=now)

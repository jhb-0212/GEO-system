"""项目业务日历：唯一时区与窗口事实源。

规则：
- 时区来自 `Project.timezone`（IANA 名称），不接受调用方偏移；
- 今天/本周按项目本地自然日计算，左闭右开；
- 时间戳存储与查询边界统一使用 UTC，DST 由 ZoneInfo 处理；
- 非法时区显式报错，不静默回退。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import Project

DEFAULT_TIMEZONE = "Asia/Shanghai"
WindowKind = Literal["today", "week"]


class ProjectTimezoneInvalid(ValueError):
    """项目时区缺失、空值或不是合法 IANA 名称。"""

    def __init__(self, name: object) -> None:
        self.name = name
        super().__init__(f"项目时区无效：{name!r}")


@dataclass(frozen=True)
class BusinessWindow:
    """左闭右开的 UTC 查询边界。"""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class ProjectCalendar:
    """一次请求内固定的项目日历；所有窗口都从同一实例派生。"""

    zone: ZoneInfo
    local_today: date
    week_start_date: date
    now: datetime

    def window(self, kind: WindowKind) -> BusinessWindow:
        if kind == "today":
            start_date, end_date = self.local_today, self.local_today + timedelta(days=1)
        elif kind == "week":
            start_date, end_date = self.week_start_date, self.week_start_date + timedelta(days=7)
        else:  # pragma: no cover - Literal 已限定
            raise ValueError(f"未知窗口类型：{kind}")
        return BusinessWindow(_local_midnight_utc(self.zone, start_date), _local_midnight_utc(self.zone, end_date))

    def trailing_days(self, days: int) -> tuple[date, date, datetime]:
        """兼容旧 `calendar_window`：最近 N 个本地自然日，结束日含端。"""
        end_date = self.local_today
        start_date = end_date - timedelta(days=max(days, 1) - 1)
        return start_date, end_date, _local_midnight_utc(self.zone, start_date)


def _normalize_now(now: datetime | None) -> datetime:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _local_midnight_utc(zone: ZoneInfo, day: date) -> datetime:
    """本地当日 00:00 的 UTC 时刻；对“零点不存在”的时区取当日首个有效时刻。

    个别时区会在 00:00 前后跳变（历史上如 America/Sao_Paulo）。此时
    `datetime.combine(day, time.min, tzinfo=zone)` 的偏移已切换到跳变后，
    往返转换即可得到当日第一个真实存在的瞬间；返回前校验日期不漂移。
    """
    local = datetime.combine(day, time.min, tzinfo=zone).replace(fold=0)
    moment = local.astimezone(UTC)
    if moment.astimezone(zone).date() != day:
        raise ProjectTimezoneInvalid(f"{zone.key} 在 {day.isoformat()} 的日界无法解析")
    return moment


def resolve_timezone(name: str | None) -> ZoneInfo:
    """严格解析；仅 `None` 表示“未配置”（新建默认），空白字符串视为脏数据。"""
    if name is None:
        return ZoneInfo(DEFAULT_TIMEZONE)
    text = str(name).strip()
    if not text:
        raise ProjectTimezoneInvalid(name)
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ProjectTimezoneInvalid(name) from exc


def project_timezone(project) -> ZoneInfo:
    return resolve_timezone(getattr(project, "timezone", None))


def local_today(zone: ZoneInfo, *, now: datetime | None = None) -> date:
    return _normalize_now(now).astimezone(zone).date()


def local_day_start_utc(zone: ZoneInfo, day: date) -> datetime:
    """某个本地自然日 00:00 对应的 UTC 时刻（DST 安全）。"""
    return _local_midnight_utc(zone, day)


def project_calendar(project, *, now: datetime | None = None) -> ProjectCalendar:
    """唯一构造入口：固定一次 now，后续窗口都从该实例派生。"""
    moment = _normalize_now(now)
    zone = project_timezone(project)
    today = moment.astimezone(zone).date()
    return ProjectCalendar(
        zone=zone,
        local_today=today,
        week_start_date=today - timedelta(days=today.weekday()),
        now=moment,
    )


def calendar_window(project, days: int, *, now: datetime | None = None) -> tuple[date, date, datetime]:
    """兼容投影：只转换 `ProjectCalendar.trailing_days` 的结果，不持有独立算法。"""
    return project_calendar(project, now=now).trailing_days(days)


def project_calendar_window(
    db, project_id, days: int, *, now: datetime | None = None
) -> tuple[date, date, datetime]:
    return calendar_window(db.get(Project, project_id), days, now=now)

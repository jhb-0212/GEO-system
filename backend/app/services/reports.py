"""月报与线索漏斗聚合：只做只读统计，口径复用现有 stats 服务。"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Channel,
    CrawlerEvent,
    Lead,
    MonitoringTask,
    Project,
    PublishReceipt,
    Question,
    TrafficEvent,
)
from app.models.enums import EnrollmentStatus, TaskStatus
from app.services.stats import geo_overview, overview


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _timezone(project: Project) -> ZoneInfo:
    try:
        return ZoneInfo(project.timezone or "Asia/Shanghai")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def resolve_date_window(
    project: Project,
    start_date: date | None,
    end_date: date | None,
) -> tuple[datetime | None, datetime | None]:
    """把项目时区的日期边界转成 UTC；起止都为空表示全部时间。"""
    tz = _timezone(project)
    start_at = (
        datetime.combine(start_date, time.min, tzinfo=tz).astimezone(timezone.utc)
        if start_date is not None
        else None
    )
    end_at = (
        datetime.combine(end_date, time.max, tzinfo=tz).astimezone(timezone.utc)
        if end_date is not None
        else None
    )
    return start_at, end_at


def month_window(project: Project, month: str | None) -> tuple[datetime, datetime, str]:
    """返回 [月初, 月末] 的 UTC 闭区间，以及 YYYY-MM 标签。"""
    tz = _timezone(project)
    if month:
        try:
            year, month_number = (int(part) for part in month.split("-", 1))
            first_day = date(year, month_number, 1)
        except (ValueError, TypeError) as exc:
            raise ValueError("month 必须是 YYYY-MM") from exc
    else:
        today = datetime.now(tz).date()
        first_day = date(today.year, today.month, 1)
    next_month = (
        date(first_day.year + 1, 1, 1)
        if first_day.month == 12
        else date(first_day.year, first_day.month + 1, 1)
    )
    start_at = datetime.combine(first_day, time.min, tzinfo=tz).astimezone(timezone.utc)
    end_at = (
        datetime.combine(next_month, time.min, tzinfo=tz).astimezone(timezone.utc)
        - timedelta(microseconds=1)
    )
    return start_at, end_at, f"{first_day.year:04d}-{first_day.month:02d}"


def _lead_filters(project_id: uuid.UUID, start_at: datetime | None, end_at: datetime | None):
    filters = [Lead.project_id == project_id]
    if start_at is not None:
        filters.append(Lead.created_at >= start_at)
    if end_at is not None:
        filters.append(Lead.created_at <= end_at)
    return filters


def _lead_totals(db: Session, filters) -> tuple[int, int, int, int, int, int]:
    rows = db.execute(
        select(
            func.count(Lead.id),
            func.coalesce(func.sum(case((Lead.is_valid.is_(True), 1), else_=0)), 0),
            func.coalesce(
                func.sum(case((Lead.enrollment_status == EnrollmentStatus.UNKNOWN, 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((Lead.enrollment_status == EnrollmentStatus.CONTACTED, 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((Lead.enrollment_status == EnrollmentStatus.ENROLLED, 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((Lead.enrollment_status == EnrollmentStatus.LOST, 1), else_=0)),
                0,
            ),
        )
        .select_from(Lead)
        .where(*filters)
    ).one()
    total, valid, unknown, contacted, enrolled, lost = (int(value or 0) for value in rows)
    return total, valid, unknown, contacted, enrolled, lost


def _lead_groups(db: Session, filters, *, dimension: str) -> list[dict]:
    """按来源/渠道/题目聚合；只返回前 30 组，避免无界明细拖慢月报。"""
    total = func.count(Lead.id)
    valid = func.coalesce(func.sum(case((Lead.is_valid.is_(True), 1), else_=0)), 0)
    contacted = func.coalesce(
        func.sum(
            case(
                (
                    Lead.enrollment_status.in_(
                        [EnrollmentStatus.CONTACTED, EnrollmentStatus.ENROLLED]
                    ),
                    1,
                ),
                else_=0,
            )
        ),
        0,
    )
    enrolled = func.coalesce(
        func.sum(case((Lead.enrollment_status == EnrollmentStatus.ENROLLED, 1), else_=0)),
        0,
    )
    if dimension == "source":
        key = func.coalesce(func.nullif(Lead.lead_source, ""), "unattributed")
        order_label = key
        statement = (
            select(key.label("key"), order_label.label("label"), total, valid, contacted, enrolled)
            .where(*filters)
            .group_by(key, order_label)
        )
    elif dimension == "channel":
        order_label = func.coalesce(Channel.name, "未归因渠道")
        statement = (
            select(
                func.coalesce(cast(Channel.id, String), "unattributed").label("key"),
                order_label.label("label"),
                total,
                valid,
                contacted,
                enrolled,
            )
            .select_from(Lead)
            .outerjoin(Channel, Channel.id == Lead.source_channel_id)
            .where(*filters)
            .group_by(Channel.id, Channel.name)
        )
    else:
        order_label = func.coalesce(
            Question.code + " · " + Question.title,
            "未归因题目",
        )
        statement = (
            select(
                func.coalesce(cast(Question.id, String), "unattributed").label("key"),
                order_label.label("label"),
                total,
                valid,
                contacted,
                enrolled,
            )
            .select_from(Lead)
            .outerjoin(Question, Question.id == Lead.source_question_id)
            .where(*filters)
            .group_by(Question.id, Question.code, Question.title)
        )
    rows = db.execute(statement.order_by(total.desc(), order_label.asc()).limit(30)).all()
    return [
        {
            "key": str(row[0]),
            "label": str(row[1]),
            "total": int(row[2] or 0),
            "valid": int(row[3] or 0),
            "contacted": int(row[4] or 0),
            "enrolled": int(row[5] or 0),
        }
        for row in rows
    ]


def _ai_attribution(
    db: Session,
    project_id: uuid.UUID,
    lead_filters: list,
    *,
    start_at: datetime | None,
    end_at: datetime | None,
) -> dict:
    """机器访问、人类访问、用户自报 AI 来源三组事实分开计数，不合成转化率。"""
    crawler_filters = [CrawlerEvent.project_id == project_id]
    traffic_filters = [TrafficEvent.project_id == project_id]
    if start_at is not None:
        crawler_filters.append(CrawlerEvent.occurred_at >= start_at)
        traffic_filters.append(TrafficEvent.occurred_at >= start_at)
    if end_at is not None:
        crawler_filters.append(CrawlerEvent.occurred_at <= end_at)
        traffic_filters.append(TrafficEvent.occurred_at <= end_at)

    crawler_events = int(
        db.scalar(select(func.count()).select_from(CrawlerEvent).where(*crawler_filters)) or 0
    )
    verified_bot_events = int(
        db.scalar(
            select(func.count())
            .select_from(CrawlerEvent)
            .where(*crawler_filters, CrawlerEvent.verified_bot.is_(True))
        )
        or 0
    )

    human_filters = [*traffic_filters, TrafficEvent.is_bot.is_(False)]
    human_visits = int(
        db.scalar(select(func.count()).select_from(TrafficEvent).where(*human_filters)) or 0
    )
    human_sessions = int(
        db.scalar(
            select(func.count(func.distinct(TrafficEvent.visitor_session_id))).where(
                *human_filters,
                TrafficEvent.visitor_session_id.is_not(None),
            )
        )
        or 0
    )

    self_reported_filter = or_(
        Lead.reported_ai_product.is_not(None),
        Lead.reported_ai_product != "",
        Lead.source_engine_id.is_not(None),
    )
    self_reported_ai_leads = int(
        db.scalar(
            select(func.count()).select_from(Lead).where(*lead_filters, self_reported_filter)
        )
        or 0
    )
    self_reported_ai_valid_leads = int(
        db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(*lead_filters, self_reported_filter, Lead.is_valid.is_(True))
        )
        or 0
    )
    return {
        "crawler_events": crawler_events,
        "verified_bot_events": verified_bot_events,
        "human_visits": human_visits,
        "human_sessions": human_sessions,
        "self_reported_ai_leads": self_reported_ai_leads,
        "self_reported_ai_valid_leads": self_reported_ai_valid_leads,
    }


def lead_funnel(
    db: Session,
    project_id: uuid.UUID,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict:
    filters = _lead_filters(project_id, start_at, end_at)
    total, valid, unknown, contacted_status, enrolled, lost = _lead_totals(db, filters)
    # 漏斗按“到达过”计算：已报名线索也视为已联系，不把状态当成互斥终态。
    contacted = contacted_status + enrolled
    stages = [
        {"key": "total", "label": "咨询总量", "count": total, "rate": _rate(total, total), "step_rate": None},
        {"key": "valid", "label": "有效线索", "count": valid, "rate": _rate(valid, total), "step_rate": _rate(valid, total)},
        {
            "key": "contacted",
            "label": "已联系",
            "count": contacted,
            "rate": _rate(contacted, total),
            "step_rate": _rate(contacted, valid),
        },
        {
            "key": "enrolled",
            "label": "已报名",
            "count": enrolled,
            "rate": _rate(enrolled, total),
            "step_rate": _rate(enrolled, contacted),
        },
    ]
    return {
        "start_at": start_at,
        "end_at": end_at,
        "total": total,
        "valid": valid,
        "contacted": contacted,
        "enrolled": enrolled,
        "lost": lost,
        "status_counts": {
            "unknown": unknown,
            "contacted": contacted_status,
            "enrolled": enrolled,
            "lost": lost,
        },
        "contact_rate": _rate(contacted, valid),
        "conversion_rate": _rate(enrolled, valid),
        "stages": stages,
        "ai_attribution": _ai_attribution(
            db, project_id, filters, start_at=start_at, end_at=end_at
        ),
        "by_source": _lead_groups(db, filters, dimension="source"),
        "by_channel": _lead_groups(db, filters, dimension="channel"),
        "by_question": _lead_groups(db, filters, dimension="question"),
    }


def monthly_report(
    db: Session,
    project: Project,
    *,
    month: str | None = None,
    include_leads: bool = True,
) -> dict:
    start_at, end_at, month_label = month_window(project, month)
    task_rows = db.execute(
        select(MonitoringTask.status, func.count(MonitoringTask.id))
        .where(
            MonitoringTask.project_id == project.id,
            MonitoringTask.created_at >= start_at,
            MonitoringTask.created_at <= end_at,
        )
        .group_by(MonitoringTask.status)
    ).all()
    status_counts = {str(status): int(count) for status, count in task_rows}
    done = status_counts.get(TaskStatus.DONE.value, 0)
    failed = status_counts.get(TaskStatus.FAILED.value, 0)
    running = status_counts.get(TaskStatus.RUNNING.value, 0)
    pending = status_counts.get(TaskStatus.PENDING.value, 0)
    task_total = done + failed + running + pending

    overview_data = overview(
        db,
        project.id,
        start_at=start_at,
        end_at=end_at,
    )
    geo_data = geo_overview(
        db,
        project.id,
        start_at=start_at,
        end_at=end_at,
    )
    published_receipts = int(
        db.scalar(
            select(func.count(func.distinct(PublishReceipt.task_id)))
            .select_from(PublishReceipt)
            .where(
                PublishReceipt.project_id == project.id,
                PublishReceipt.received_at >= start_at,
                PublishReceipt.received_at <= end_at,
            )
        )
        or 0
    )
    return {
        "month": month_label,
        "period_start": start_at,
        "period_end": end_at,
        "tasks": {
            "total": task_total,
            "done": done,
            "failed": failed,
            "running": running,
            "pending": pending,
            "completion_rate": _rate(done + failed, task_total),
        },
        "answers": {
            "valid_answers": overview_data["valid_answers"],
            "brand_mentioned_answers": overview_data["brand_mentioned_answers"],
            "citation_answers": overview_data["citation_answers"],
            "brand_mention_rate": overview_data["brand_mention_rate"],
            "citation_rate": overview_data["citation_rate"],
            "total_samples": geo_data["counts"]["total_samples"],
            "failure_rate": geo_data["failure_rate"],
            "fresh_24h_rate": geo_data["fresh_24h_rate"],
            "prompt_coverage": geo_data["prompt_coverage"],
        },
        "leads": lead_funnel(db, project.id, start_at=start_at, end_at=end_at) if include_leads else None,
        "published_receipts": published_receipts,
    }

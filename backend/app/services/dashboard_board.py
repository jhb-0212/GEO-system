"""GEO 数据大屏：四个数 + 榜单 + 收录曲线 + 平台占比 + 报表明细 + 线索事件。

和 B1 双轨大屏的取舍相反：这一屏是**对外演示**用的单一视图，所以每个数都只取一条口径，
不并列两套分母；口径写在每张卡的 note 和末尾 notes 里，前端可以直接贴到汇报页。

演示占位规则：某个指标在本项目完全为 0（既无累计也无窗口新增）时，返回一组**确定性样例值**
并标 `source="demo"`。样例值不写库、不参与任何统计，前端必须在卡片上显式标「演示」；
只要有任何真实记录，就整项切回真实值，绝不出现「真实 3 条 + 样例 19,193」的混合数。

隐私：线索事件只给 `visitor_ip_hash` 前 8 位摘要，`traffic_events` / `leads` 都不存 IP 原文，
这一屏不回补明文，也不提供「查看完整 IP」入口。
"""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    Keyword,
    Lead,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionKeyword,
    QuestionVersion,
    TrafficEvent,
)
from app.models.enums import AnswerKind, EngineEntryType
from app.services.stats import CONFIRMED_REVIEW_STATUS, VALID_SAMPLE_STATUSES
from app.services.time_windows import project_calendar

UNKNOWN_LABEL = "未填写"
DIRECT_LABEL = "直接访问"
ALL_ENGINES_LABEL = "全部"

# 样例值对齐演示稿：训练词 4、推荐词 833（近 30 天 +789）、累计收录 19,193（近 30 天 +789）、
# 线索事件 507。仅当真实记录为 0 时使用。
DEMO_KPIS: dict[str, dict[str, int]] = {
    "training_words": {"total": 4, "window": 0},
    "recommended_words": {"total": 833, "window": 789},
    "indexed_total": {"total": 19193, "window": 789},
    "lead_events": {"total": 507, "window": 31},
}

# 报表明细里「AI 回答里出现了谁」只能落到引用证据：标题 → 站点名 → 域名逐级兜底。


def _pages(total: int, page_size: int) -> int:
    return max(1, math.ceil(total / page_size)) if total else 1


def _demo_spark(seed: str, total: int, days: int) -> list[int]:
    """确定性样例柱：同一项目同一天刷新看到同一组柱，避免演示时数字乱跳。"""
    if days <= 0:
        return []
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    weights = [1 + digest[index % len(digest)] % 7 for index in range(days)]
    weight_sum = sum(weights)
    values = [int(total * weight / weight_sum) for weight in weights]
    values[-1] += total - sum(values)
    return values


def _daily_map(db: Session, project_id: uuid.UUID, *, column, model, since: datetime, zone) -> dict[date, int]:
    """按项目本地自然日计数；窗口边界仍是 UTC，只有分组落到本地日。"""
    day_expr = func.date(func.timezone(zone.key, column))
    rows = db.execute(
        select(day_expr.label("day"), func.count())
        .select_from(model)
        .where(model.project_id == project_id, column >= since)
        .group_by(day_expr)
    ).all()
    daily: dict[date, int] = {}
    for raw_day, count in rows:
        if raw_day is None:
            continue
        day = date.fromisoformat(raw_day) if isinstance(raw_day, str) else raw_day
        daily[day] = int(count)
    return daily


def _spark(daily: dict[date, int], start_date: date, days: int) -> list[int]:
    return [int(daily.get(start_date + timedelta(days=index), 0)) for index in range(days)]


def _kpi(
    key: str,
    label: str,
    unit: str,
    *,
    total: int,
    window: int,
    spark: list[int],
    days: int,
    note: str,
    seed: str,
) -> dict:
    if total > 0:
        return {
            "key": key,
            "label": label,
            "unit": unit,
            "value": total,
            "window_value": window,
            "window_days": days,
            "spark": spark,
            "source": "real",
            "note": note,
        }
    demo = DEMO_KPIS[key]
    demo_window = int(round(demo["window"] * days / 30)) if demo["window"] else 0
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "value": demo["total"],
        "window_value": demo_window,
        "window_days": days,
        "spark": _demo_spark(seed, demo_window, days),
        "source": "demo",
        "note": "本项目暂无记录，当前为本屏内置的演示样例，不是真实统计。",
    }


def _top_keywords(db: Session, project_id: uuid.UUID, *, since: datetime, limit: int = 10) -> dict:
    question_counts = db.execute(
        select(QuestionKeyword.keyword_id, func.count(func.distinct(QuestionKeyword.question_id)))
        .where(QuestionKeyword.project_id == project_id)
        .group_by(QuestionKeyword.keyword_id)
    ).all()
    citation_counts = db.execute(
        select(
            QuestionKeyword.keyword_id,
            func.count(func.distinct(MonitoringCitation.id)),
        )
        .select_from(MonitoringCitation)
        .join(MonitoringSample, MonitoringSample.id == MonitoringCitation.sample_id)
        .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
        .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
        .join(QuestionKeyword, QuestionKeyword.question_id == QuestionVersion.question_id)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringSample.sampled_at >= since,
        )
        .group_by(QuestionKeyword.keyword_id)
    ).all()
    questions = {row[0]: int(row[1]) for row in question_counts}
    citations = {row[0]: int(row[1]) for row in citation_counts}

    keywords = db.execute(
        select(Keyword.id, Keyword.name).where(
            Keyword.project_id == project_id,
            Keyword.is_active.is_(True),
        )
    ).all()
    rows = [
        {
            "keyword_id": str(keyword_id),
            "name": name,
            "questions": questions.get(keyword_id, 0),
            "citations": citations.get(keyword_id, 0),
        }
        for keyword_id, name in keywords
    ]
    rows.sort(key=lambda row: (-row["questions"], -row["citations"], row["name"]))
    items = [{"rank": index + 1, **row} for index, row in enumerate(rows[:limit])]
    return {
        "items": items,
        "total": len(rows),
        "max": max((row["questions"] for row in rows), default=0),
    }


def _engine_share(db: Session, project_id: uuid.UUID, *, since: datetime) -> dict:
    rows = db.execute(
        select(AiEngine.id, AiEngine.name, func.count(func.distinct(MonitoringSample.id)))
        .select_from(MonitoringSample)
        .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(
            MonitoringSample.project_id == project_id,
            MonitoringSample.status.in_(VALID_SAMPLE_STATUSES),
            MonitoringSample.sampled_at >= since,
        )
        .group_by(AiEngine.id, AiEngine.name)
    ).all()
    items = [
        {"engine_id": str(engine_id), "engine_name": name, "value": int(count)}
        for engine_id, name, count in rows
    ]
    items.sort(key=lambda item: (-item["value"], item["engine_name"]))
    total = sum(item["value"] for item in items)
    for item in items:
        item["share"] = (item["value"] / total) if total else None
    return {"items": items, "total": total}


def _entry_type_conditions(device: str) -> list:
    """采集端口径：pc = 网页用户端；mobile = 客户端 + 应用内搜索；all 不过滤（官方 API 也算全部端）。"""
    if device == "pc":
        return [AiEngineEntry.entry_type == EngineEntryType.WEB_USER]
    if device == "mobile":
        return [AiEngineEntry.entry_type.in_([EngineEntryType.APP_USER, EngineEntryType.APP_SEARCH])]
    return []


def _report_engines(db: Session, project_id: uuid.UUID, *, since: datetime, device: str = "all") -> dict:
    scope = (
        select(AiEngine.id, AiEngine.name, func.count(func.distinct(MonitoringCitation.id)))
        .select_from(MonitoringCitation)
        .join(MonitoringSample, MonitoringSample.id == MonitoringCitation.sample_id)
        .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringSample.sampled_at >= since,
        )
    )
    device_conditions = _entry_type_conditions(device)
    if device_conditions:
        scope = scope.where(*device_conditions)
    rows = db.execute(scope.group_by(AiEngine.id, AiEngine.name)).all()
    items = [
        {"engine_id": str(engine_id), "engine_name": name, "value": int(count)}
        for engine_id, name, count in rows
    ]
    items.sort(key=lambda item: (-item["value"], item["engine_name"]))
    return {"items": items, "total": sum(item["value"] for item in items)}


def _keyword_names(db: Session, project_id: uuid.UUID, question_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not question_ids:
        return {}
    rows = db.execute(
        select(QuestionKeyword.question_id, Keyword.name, Keyword.priority)
        .select_from(QuestionKeyword)
        .join(Keyword, Keyword.id == QuestionKeyword.keyword_id)
        .where(
            QuestionKeyword.project_id == project_id,
            QuestionKeyword.question_id.in_(question_ids),
        )
        .order_by(Keyword.priority, Keyword.name)
    ).all()
    names: dict[uuid.UUID, str] = {}
    for question_id, name, _priority in rows:
        names.setdefault(question_id, name)
    return names


def _report_page(
    db: Session,
    project_id: uuid.UUID,
    *,
    since: datetime,
    engine_id: uuid.UUID | None,
    page: int,
    page_size: int,
    kind: str = "all",
    device: str = "all",
) -> dict:
    scope = (
        select(MonitoringCitation.id, MonitoringCitation.title, MonitoringCitation.site_name, MonitoringCitation.domain,
               MonitoringCitation.normalized_url, MonitoringCitation.raw_url, MonitoringCitation.review_status,
               QuestionVersion.question_id, Question.title.label("question_title"), AiEngine.name.label("engine_name"),
               MonitoringSample.sampled_at, MonitoringSample.answer_kind, MonitoringSample.brand_mentioned,
               Question.intent)
        .select_from(MonitoringCitation)
        .join(MonitoringSample, MonitoringSample.id == MonitoringCitation.sample_id)
        .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
        .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
        .join(Question, Question.id == QuestionVersion.question_id)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringSample.sampled_at >= since,
        )
    )
    if engine_id is not None:
        scope = scope.where(AiEngine.id == engine_id)
    # 报表类型：search/qa 按样本答案口径分（检索结果 vs 生成回答），intent 看问题意图，brand 看是否命中品牌。
    if kind == "search":
        scope = scope.where(MonitoringSample.answer_kind == AnswerKind.SEARCH_RESULT)
    elif kind == "qa":
        scope = scope.where(MonitoringSample.answer_kind == AnswerKind.ANSWER)
    elif kind == "intent":
        scope = scope.where(Question.intent.is_not(None), func.length(func.trim(Question.intent)) > 0)
    elif kind == "brand":
        scope = scope.where(MonitoringSample.brand_mentioned.is_(True))
    device_conditions = _entry_type_conditions(device)
    if device_conditions:
        scope = scope.where(*device_conditions)
    total = int(db.scalar(select(func.count()).select_from(scope.subquery())) or 0)
    rows = db.execute(
        scope.order_by(MonitoringSample.sampled_at.desc(), MonitoringCitation.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    question_ids = list({row.question_id for row in rows})
    keyword_names = _keyword_names(db, project_id, question_ids)

    items = []
    for row in rows:
        voucher = row.normalized_url or row.raw_url
        official = f"https://{row.domain.strip()}" if row.domain and row.domain.strip() else None
        items.append(
            {
                "citation_id": str(row.id),
                "training_word": keyword_names.get(row.question_id) or row.question_title,
                "answer_entity": row.title or row.site_name or row.domain or "—",
                "platform": row.engine_name,
                "voucher_url": voucher,
                "official_url": official,
                "reviewed": row.review_status == CONFIRMED_REVIEW_STATUS,
                "occurred_at": row.sampled_at.isoformat() if row.sampled_at else None,
            }
        )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": _pages(total, page_size),
        "rows": items,
        "kind": kind,
        "device": device,
    }


def _lead_events(db: Session, project_id: uuid.UUID, *, page: int, page_size: int) -> dict:
    """访问事件与表单线索合并成一列，按时间倒序；地区/IP 摘要/来源/落地页同列展示。"""
    traffic = select(
        literal("访问官网").label("event"),
        TrafficEvent.visitor_region.label("region"),
        TrafficEvent.visitor_ip_hash.label("ip_hash"),
        TrafficEvent.utm_source.label("source"),
        TrafficEvent.landing_url.label("url"),
        TrafficEvent.occurred_at.label("occurred_at"),
    ).where(TrafficEvent.project_id == project_id, TrafficEvent.is_bot.is_(False))
    leads = select(
        literal("提交线索").label("event"),
        Lead.visitor_region.label("region"),
        Lead.ip_hash.label("ip_hash"),
        Lead.lead_source.label("source"),
        Lead.landing_url.label("url"),
        Lead.created_at.label("occurred_at"),
    ).where(Lead.project_id == project_id)
    merged = union_all(traffic, leads).subquery()
    total = int(db.scalar(select(func.count()).select_from(merged)) or 0)
    rows = db.execute(
        select(merged)
        .order_by(merged.c.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = []
    for row in rows:
        masked = f"{row.ip_hash[:8]}…" if row.ip_hash else "—"
        items.append(
            {
                "event": row.event,
                "region": row.region or UNKNOWN_LABEL,
                "ip_masked": masked,
                "source": row.source or DIRECT_LABEL,
                "url": row.url,
                "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            }
        )
    return {"total": total, "page": page, "page_size": page_size, "pages": _pages(total, page_size), "rows": items}


def board_snapshot(
    db: Session,
    project_id: uuid.UUID,
    *,
    days: int = 30,
    engine_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 10,
    report_kind: str = "all",
    device: str = "all",
    lead_page: int = 1,
    lead_page_size: int = 10,
    now: datetime | None = None,
) -> dict:
    days = max(1, min(days, 365))
    page_size = max(1, min(page_size, 50))
    lead_page_size = max(1, min(lead_page_size, 50))
    # 项目日历只取一次：窗口边界、时区、日期序列都从同一实例派生，避免跨零点时前后不一致。
    calendar = project_calendar(db.get(Project, project_id), now=now)
    start_date, end_date, since = calendar.trailing_days(days)
    zone = calendar.zone
    dates = [start_date + timedelta(days=index) for index in range(days)]

    keyword_daily = _daily_map(db, project_id, column=Keyword.created_at, model=Keyword, since=since, zone=zone)
    question_daily = _daily_map(db, project_id, column=Question.created_at, model=Question, since=since, zone=zone)
    citation_daily = _daily_map(
        db, project_id, column=MonitoringCitation.created_at, model=MonitoringCitation, since=since, zone=zone
    )
    traffic_daily = _daily_map(
        db, project_id, column=TrafficEvent.occurred_at, model=TrafficEvent, since=since, zone=zone
    )
    lead_daily = _daily_map(db, project_id, column=Lead.created_at, model=Lead, since=since, zone=zone)

    keyword_total = int(
        db.scalar(
            select(func.count()).select_from(Keyword).where(
                Keyword.project_id == project_id, Keyword.is_active.is_(True)
            )
        )
        or 0
    )
    question_total = int(db.scalar(select(func.count()).select_from(Question).where(Question.project_id == project_id)) or 0)
    citation_total = int(
        db.scalar(select(func.count()).select_from(MonitoringCitation).where(MonitoringCitation.project_id == project_id))
        or 0
    )
    traffic_total = int(
        db.scalar(
            select(func.count()).select_from(TrafficEvent).where(
                TrafficEvent.project_id == project_id, TrafficEvent.is_bot.is_(False)
            )
        )
        or 0
    )
    lead_total = int(db.scalar(select(func.count()).select_from(Lead).where(Lead.project_id == project_id)) or 0)

    seed_prefix = f"{project_id}:{days}"
    kpis = [
        _kpi(
            "training_words",
            "训练词总量",
            "个",
            total=keyword_total,
            window=sum(keyword_daily.values()),
            spark=_spark(keyword_daily, start_date, days),
            days=days,
            note="启用中的目标关键词（keywords）个数；不含题库问题。",
            seed=f"{seed_prefix}:training_words",
        ),
        _kpi(
            "recommended_words",
            "推荐词总量",
            "个",
            total=question_total,
            window=sum(question_daily.values()),
            spark=_spark(question_daily, start_date, days),
            days=days,
            note="题库问题（questions）个数，一条问题算一个推荐词；不数 AI 回答里的自由文本。",
            seed=f"{seed_prefix}:recommended_words",
        ),
        _kpi(
            "indexed_total",
            "累计收录总量",
            "条",
            total=citation_total,
            window=sum(citation_daily.values()),
            spark=_spark(citation_daily, start_date, days),
            days=days,
            note="AI 回答里带出的引用证据（monitoring_citations）累计条数；不是发布收录检测通过数。",
            seed=f"{seed_prefix}:indexed_total",
        ),
        _kpi(
            "lead_events",
            "线索事件量",
            "条",
            total=traffic_total + lead_total,
            window=sum(traffic_daily.values()) + sum(lead_daily.values()),
            spark=[
                int(traffic_daily.get(day, 0)) + int(lead_daily.get(day, 0)) for day in dates
            ],
            days=days,
            note="非机器人访问事件 + 表单线索之和；两类事件分母不同，本屏不计算转化率。",
            seed=f"{seed_prefix}:lead_events",
        ),
    ]

    running = 0
    series = []
    for day in dates:
        running += int(citation_daily.get(day, 0))
        series.append({"date": day.isoformat(), "value": running})
    if citation_total == 0:
        demo_values = _demo_spark(f"{seed_prefix}:indexed_series", 789, days)
        running = 0
        series = []
        for day, step in zip(dates, demo_values):
            running += step
            series.append({"date": day.isoformat(), "value": running})
        series_source = "demo"
    else:
        series_source = "real"

    report_engines = _report_engines(db, project_id, since=since, device=device)
    return {
        "project_window": {
            "days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timezone": zone.key,
        },
        "kpis": kpis,
        "has_demo": any(item["source"] == "demo" for item in kpis) or series_source == "demo",
        "top_keywords": _top_keywords(db, project_id, since=since),
        "indexed_series": {"source": series_source, "items": series},
        "engine_share": _engine_share(db, project_id, since=since),
        "report": {
            **_report_page(
                db,
                project_id,
                since=since,
                engine_id=engine_id,
                page=page,
                page_size=page_size,
                kind=report_kind,
                device=device,
            ),
            "engines": [
                {"engine_id": None, "engine_name": ALL_ENGINES_LABEL, "value": report_engines["total"]},
                *report_engines["items"],
            ],
            "selected_engine_id": str(engine_id) if engine_id else None,
        },
        "lead_events": _lead_events(db, project_id, page=lead_page, page_size=lead_page_size),
        "notes": [
            "训练词 = 启用中的目标关键词；推荐词 = 题库问题；两者都是库内记录数，不是 AI 回答里的词频。",
            "累计收录 = 引用证据条数；折线是窗口内按日累计，窗口最后一天的值应等于该窗口新增总数。",
            "线索事件 = 非机器人访问事件 + 表单线索；只做计数，不做转化率，两类事件分母不同。",
            "线索列表的 IP 只显示哈希前 8 位：traffic_events / leads 都不存 IP 原文，本屏不回补明文。",
            "卡片右上角出现「演示」时，该卡全部为本屏内置样例（无任何真实记录），不与真实数混合。",
            "平台占比按近 N 天有效样本数；报表明细按引用条数，两者分母不同，不互相换算。",
        ],
    }

"""异常预警：规则计算、24 小时去重、webhook 推送。

口径：
- 提及率 = brand_mentioned 非空的 hit 样本中 True 占比；
- 推荐率 = brand_recommendation 非空的样本中 True 占比；
- 竞品反超 = 品牌有排名且竞品最小名次更靠前的样本数；
- 负面占比 = 已标注情绪中 negative 占比；
- 采集失败率 = failed 样本 / 全部样本。
当前窗口与上一个等长窗口比较；任一侧样本/标注不足则不触发，不把未知写成 0。
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.models import (
    AlertEvent,
    AlertRule,
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringSample,
    SentimentLabel,
)
from app.models.enums import AlertEventStatus, AlertRuleCode, AlertSeverity, SampleStatus, SentimentPolarity
from app.services.state_machine import ensure_alert_event_transition

logger = logging.getLogger(__name__)

DEFAULT_RULES: dict[AlertRuleCode, dict[str, Any]] = {
    AlertRuleCode.MENTION_RATE_DROP: {
        "name": "品牌提及率下降",
        "severity": AlertSeverity.WARNING,
        "thresholds": {"window_days": 7, "min_samples": 5, "drop_abs": 0.15},
    },
    AlertRuleCode.RECOMMENDATION_RATE_DROP: {
        "name": "品牌被推荐率下降",
        "severity": AlertSeverity.WARNING,
        "thresholds": {"window_days": 7, "min_samples": 3, "drop_abs": 0.15},
    },
    AlertRuleCode.COMPETITOR_OUTRANK: {
        "name": "竞品反超次数升高",
        "severity": AlertSeverity.WARNING,
        "thresholds": {"window_days": 7, "min_samples": 3, "outrank_min": 3},
    },
    AlertRuleCode.NEGATIVE_SHARE_RISE: {
        "name": "负面占比上升",
        "severity": AlertSeverity.WARNING,
        "thresholds": {"window_days": 7, "min_labels": 5, "rise_abs": 0.1},
    },
    AlertRuleCode.COLLECTION_FAILURE_RATE: {
        "name": "采集失败率过高",
        "severity": AlertSeverity.CRITICAL,
        "thresholds": {"window_days": 7, "min_samples": 5, "max_rate": 0.2},
    },
}


def ensure_default_rules(db: Session, project_id: uuid.UUID) -> list[AlertRule]:
    existing = {
        rule.code: rule
        for rule in db.scalars(select(AlertRule).where(AlertRule.project_id == project_id))
    }
    for code, config in DEFAULT_RULES.items():
        if code in existing:
            continue
        rule = AlertRule(
            project_id=project_id,
            code=code,
            name=config["name"],
            severity=config["severity"],
            is_enabled=True,
            thresholds=dict(config["thresholds"]),
        )
        db.add(rule)
        existing[code] = rule
    db.flush()
    return [existing[code] for code in DEFAULT_RULES]


def _period(db: Session, project_id: uuid.UUID, start: datetime, end: datetime) -> dict[str, Any]:
    samples = list(db.scalars(select(MonitoringSample).where(
        MonitoringSample.project_id == project_id,
        MonitoringSample.sampled_at >= start,
        MonitoringSample.sampled_at < end,
    )))
    total = len(samples)
    failed = sum(1 for sample in samples if sample.status == SampleStatus.FAILED)
    answered = [sample for sample in samples if sample.status == SampleStatus.HIT and sample.brand_mentioned is not None]
    mentioned = sum(1 for sample in answered if sample.brand_mentioned)
    known_recommendation = [sample for sample in answered if sample.brand_recommendation is not None]
    recommended = sum(1 for sample in known_recommendation if sample.brand_recommendation)
    sample_ids = [sample.id for sample in samples]
    outrank = 0
    if sample_ids:
        brand_ranks = {
            sample.id: sample.brand_list_rank
            for sample in samples
            if sample.status == SampleStatus.HIT and sample.brand_list_rank is not None
        }
        competitor_rows = db.execute(
            select(MonitoringCompetitorMention.sample_id, func.min(MonitoringCompetitorMention.position))
            .where(MonitoringCompetitorMention.sample_id.in_(list(brand_ranks)))
            .group_by(MonitoringCompetitorMention.sample_id)
        ).all()
        outrank = sum(
            1 for sample_id, best_position in competitor_rows
            if best_position is not None and best_position < brand_ranks[sample_id]
        )
    labels = db.execute(
        select(SentimentLabel.polarity, func.count())
        .join(MonitoringCitation, MonitoringCitation.id == SentimentLabel.citation_id)
        .where(
            MonitoringCitation.sample_id.in_(sample_ids),
            SentimentLabel.polarity.is_not(None),
        )
        .group_by(SentimentLabel.polarity)
    ).all() if sample_ids else []
    label_total = sum(count for _, count in labels)
    negative = sum(count for polarity, count in labels if polarity == SentimentPolarity.NEGATIVE)
    return {
        "total": total,
        "failed": failed,
        "answered": len(answered),
        "mentioned": mentioned,
        "known_recommendation": len(known_recommendation),
        "recommended": recommended,
        "outrank": outrank,
        "labels": label_total,
        "negative": negative,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _dedupe_key(code: AlertRuleCode, now: datetime, hours: int) -> str:
    bucket = int(now.timestamp() // (hours * 3600))
    return f"{code.value}:{bucket}"


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:40]


def _send_webhook(payload: dict[str, Any]) -> tuple[str, datetime | None]:
    url = settings.task_alert_webhook
    if not url:
        return "not_configured", None
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - 部署方配置
            response.read()
        return "sent", datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001 - 外部 webhook 不可用不影响事件入库
        logger.warning("alert webhook failed", extra={"fields": {"error": str(exc)}})
        return "failed", None


def evaluate_alerts(db: Session, project_id: uuid.UUID, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    rules = ensure_default_rules(db, project_id)
    events: list[AlertEvent] = []
    for rule in rules:
        if not rule.is_enabled:
            continue
        thresholds = rule.thresholds or {}
        window_days = int(thresholds.get("window_days", 7))
        current = _period(db, project_id, now - timedelta(days=window_days), now)
        previous = _period(
            db, project_id, now - timedelta(days=window_days * 2), now - timedelta(days=window_days)
        )
        hit: dict[str, Any] | None = None
        if rule.code == AlertRuleCode.MENTION_RATE_DROP:
            if current["answered"] >= int(thresholds.get("min_samples", 5)) and previous["answered"] >= int(thresholds.get("min_samples", 5)):
                current_rate = _ratio(current["mentioned"], current["answered"])
                previous_rate = _ratio(previous["mentioned"], previous["answered"])
                if current_rate is not None and previous_rate is not None and previous_rate - current_rate >= float(thresholds.get("drop_abs", 0.15)):
                    hit = {
                        "title": "品牌提及率较上一周期明显下降",
                        "metric": current_rate,
                        "baseline": previous_rate,
                        "message": f"近 {window_days} 天提及率 {current_rate:.1%}，上一周期 {previous_rate:.1%}，下降 {previous_rate - current_rate:.1%}。",
                    }
        elif rule.code == AlertRuleCode.RECOMMENDATION_RATE_DROP:
            if current["known_recommendation"] >= int(thresholds.get("min_samples", 3)) and previous["known_recommendation"] >= int(thresholds.get("min_samples", 3)):
                current_rate = _ratio(current["recommended"], current["known_recommendation"])
                previous_rate = _ratio(previous["recommended"], previous["known_recommendation"])
                if current_rate is not None and previous_rate is not None and previous_rate - current_rate >= float(thresholds.get("drop_abs", 0.15)):
                    hit = {
                        "title": "品牌被推荐率较上一周期明显下降",
                        "metric": current_rate,
                        "baseline": previous_rate,
                        "message": f"近 {window_days} 天被推荐率 {current_rate:.1%}（{current['recommended']}/{current['known_recommendation']}），上一周期 {previous_rate:.1%}。",
                    }
        elif rule.code == AlertRuleCode.COMPETITOR_OUTRANK:
            if current["outrank"] >= int(thresholds.get("outrank_min", 3)):
                hit = {
                    "title": "竞品排名反超品牌",
                    "metric": float(current["outrank"]),
                    "baseline": float(previous["outrank"]),
                    "message": f"近 {window_days} 天有 {current['outrank']} 个样本竞品名次比品牌更靠前。",
                }
        elif rule.code == AlertRuleCode.NEGATIVE_SHARE_RISE:
            if current["labels"] >= int(thresholds.get("min_labels", 5)) and previous["labels"] >= int(thresholds.get("min_labels", 5)):
                current_rate = _ratio(current["negative"], current["labels"])
                previous_rate = _ratio(previous["negative"], previous["labels"])
                if current_rate is not None and previous_rate is not None and current_rate - previous_rate >= float(thresholds.get("rise_abs", 0.1)):
                    hit = {
                        "title": "引用负面占比上升",
                        "metric": current_rate,
                        "baseline": previous_rate,
                        "message": f"近 {window_days} 天负面占比 {current_rate:.1%}（{current['negative']}/{current['labels']}），上一周期 {previous_rate:.1%}。",
                    }
        elif rule.code == AlertRuleCode.COLLECTION_FAILURE_RATE:
            if current["total"] >= int(thresholds.get("min_samples", 5)):
                current_rate = _ratio(current["failed"], current["total"])
                if current_rate is not None and current_rate >= float(thresholds.get("max_rate", 0.2)):
                    hit = {
                        "title": "采集失败率超过阈值",
                        "metric": current_rate,
                        "baseline": _ratio(previous["failed"], previous["total"]),
                        "message": f"近 {window_days} 天采集失败 {current['failed']}/{current['total']}（{current_rate:.1%}），阈值 {float(thresholds.get('max_rate', 0.2)):.0%}。",
                    }
        if not hit:
            continue
        dedupe_key = _dedupe_key(rule.code, now, 24)
        existing = db.scalar(select(AlertEvent).where(
            AlertEvent.project_id == project_id,
            AlertEvent.rule_id == rule.id,
            AlertEvent.dedupe_key == dedupe_key,
        ))
        payload = {
            "rule_code": rule.code.value,
            "severity": rule.severity.value,
            "metric_value": hit["metric"],
            "baseline_value": hit["baseline"],
            "current_samples": current["total"],
            "previous_samples": previous["total"],
            "fingerprint": _fingerprint(f"{rule.code.value}|{dedupe_key}"),
        }
        if existing:
            existing.trigger_count += 1
            existing.last_seen_at = now
            existing.metric_value = hit["metric"]
            db.flush()
            events.append(existing)
            continue
        event = AlertEvent(
            project_id=project_id,
            rule_id=rule.id,
            code=rule.code,
            severity=rule.severity,
            status=AlertEventStatus.OPEN,
            dedupe_key=dedupe_key,
            title=hit["title"],
            message=hit["message"],
            metric_value=hit["metric"],
            baseline_value=hit["baseline"],
            current_samples=current["total"],
            baseline_samples=previous["total"],
            trigger_count=1,
            triggered_at=now,
            last_seen_at=now,
            payload=payload,
        )
        db.add(event)
        db.flush()
        status, sent_at = _send_webhook({"event": "geo_alert", "project_id": str(project_id), **payload, "title": hit["title"], "message": hit["message"]})
        event.webhook_status = status
        event.webhook_sent_at = sent_at
        db.flush()
        events.append(event)
    db.commit()
    return [event_payload(event) for event in events]


def event_payload(event: AlertEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "rule_id": str(event.rule_id),
        "code": event.code.value,
        "severity": event.severity.value,
        "status": event.status.value,
        "title": event.title,
        "message": event.message,
        "metric_value": float(event.metric_value) if event.metric_value is not None else None,
        "baseline_value": float(event.baseline_value) if event.baseline_value is not None else None,
        "current_samples": event.current_samples,
        "baseline_samples": event.baseline_samples,
        "trigger_count": event.trigger_count,
        "dedupe_key": event.dedupe_key,
        "triggered_at": event.triggered_at.isoformat() if event.triggered_at else None,
        "last_seen_at": event.last_seen_at.isoformat() if event.last_seen_at else None,
        "acknowledged_at": event.acknowledged_at.isoformat() if event.acknowledged_at else None,
        "note": event.note,
        "webhook_status": event.webhook_status,
        "payload": event.payload,
    }


def rule_payload(rule: AlertRule) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "code": rule.code.value,
        "name": rule.name,
        "severity": rule.severity.value,
        "is_enabled": rule.is_enabled,
        "thresholds": rule.thresholds,
    }


def load_rule(db: Session, project_id: uuid.UUID, rule_id: uuid.UUID) -> AlertRule:
    """按项目范围取规则；不存在抛 404 级错误，不返回 None 让调用方自己猜。"""
    rule = db.scalar(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.project_id == project_id)
    )
    if rule is None:
        raise AppError("预警规则不存在", code="alert_rule_missing")
    return rule


def apply_rule_update(
    db: Session,
    rule: AlertRule,
    *,
    is_enabled: bool | None = None,
    severity: AlertSeverity | None = None,
    thresholds: dict[str, Any] | None = None,
) -> AlertRule:
    """改规则：阈值按 key 合并而不是整体覆盖，避免漏传的 key 被抹成默认。"""
    if is_enabled is not None:
        rule.is_enabled = is_enabled
    if severity is not None:
        rule.severity = severity
    if thresholds is not None:
        rule.thresholds = {**(rule.thresholds or {}), **thresholds}
    db.flush()
    return rule


def require_event(db: Session, project_id: uuid.UUID, event_id: uuid.UUID) -> AlertEvent:
    event = db.scalar(
        select(AlertEvent).where(AlertEvent.id == event_id, AlertEvent.project_id == project_id)
    )
    if event is None:
        raise AppError("预警事件不存在", code="alert_event_missing")
    return event


def page_events(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: AlertEventStatus | None = None,
    code: AlertRuleCode | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AlertEvent], int]:
    filters = [AlertEvent.project_id == project_id]
    if status is not None:
        filters.append(AlertEvent.status == status)
    if code is not None:
        filters.append(AlertEvent.code == code)
    rows = list(
        db.scalars(
            select(AlertEvent).where(*filters)
            .order_by(AlertEvent.triggered_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    )
    total = db.scalar(select(func.count()).select_from(AlertEvent).where(*filters)) or 0
    return rows, total


def acknowledge_event(db: Session, event: AlertEvent, *, actor_id: uuid.UUID, note: str | None) -> AlertEvent:
    event.status = ensure_alert_event_transition(event.status, AlertEventStatus.ACKNOWLEDGED)
    event.acknowledged_by = actor_id
    event.acknowledged_at = datetime.now(timezone.utc)
    event.note = note
    db.flush()
    return event


def resolve_event(db: Session, event: AlertEvent) -> AlertEvent:
    event.status = ensure_alert_event_transition(event.status, AlertEventStatus.RESOLVED)
    db.flush()
    return event

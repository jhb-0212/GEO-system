"""预警规则与事件 API。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, ok, ok_page
from app.core.errors import AppError
from app.db.session import get_db
from app.models import AlertEvent, AlertRule
from app.models.enums import AlertEventStatus, AlertRuleCode
from app.schemas import AlertEvaluateRequest, AlertEventAck, AlertRuleUpdate
from app.services import alerts
from app.services.state_machine import ensure_alert_event_transition
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/alerts",
    tags=["异常预警"],
    responses=COMMON_ERRORS,
)


@router.get("/rules")
def list_rules(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    rules = alerts.ensure_default_rules(db, ctx.project.id)
    db.commit()
    return ok([alerts.rule_payload(rule) for rule in rules])


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: uuid.UUID,
    body: AlertRuleUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    rule = db.scalar(select(AlertRule).where(
        AlertRule.id == rule_id, AlertRule.project_id == ctx.project.id
    ))
    if rule is None:
        raise AppError("预警规则不存在", code="alert_rule_missing")
    if body.is_enabled is not None:
        rule.is_enabled = body.is_enabled
    if body.severity is not None:
        rule.severity = body.severity
    if body.thresholds is not None:
        merged = {**(rule.thresholds or {}), **body.thresholds}
        rule.thresholds = merged
    db.flush()
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="alert.rule.update", target_type="alert_rule", target_id=rule.id,
        payload={"is_enabled": rule.is_enabled, "severity": rule.severity.value, "thresholds": rule.thresholds},
    )
    db.commit()
    return ok(alerts.rule_payload(rule))


@router.get("/events")
def list_events(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    status: AlertEventStatus | None = None,
    code: AlertRuleCode | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [AlertEvent.project_id == ctx.project.id]
    if status is not None:
        filters.append(AlertEvent.status == status)
    if code is not None:
        filters.append(AlertEvent.code == code)
    rows = db.scalars(
        select(AlertEvent).where(*filters)
        .order_by(AlertEvent.triggered_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    total = db.query(AlertEvent).filter(*filters).count()
    return ok_page([alerts.event_payload(row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("/evaluate")
def evaluate(
    body: AlertEvaluateRequest,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    events = alerts.evaluate_alerts(db, ctx.project.id)
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="alert.evaluate", target_type="alert_rule", target_id=None,
        payload={"events": len(events), "dry_run": body.dry_run},
    )
    db.commit()
    return ok({"events": events, "count": len(events)})


@router.post("/events/{event_id}/ack")
def acknowledge(
    event_id: uuid.UUID,
    body: AlertEventAck,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    event = db.scalar(select(AlertEvent).where(
        AlertEvent.id == event_id, AlertEvent.project_id == ctx.project.id
    ))
    if event is None:
        raise AppError("预警事件不存在", code="alert_event_missing")
    event.status = ensure_alert_event_transition(
        event.status, AlertEventStatus.ACKNOWLEDGED
    )
    event.acknowledged_by = ctx.user.id
    event.acknowledged_at = alerts.datetime.now(alerts.timezone.utc)
    event.note = body.note
    db.flush()
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="alert.event.ack", target_type="alert_event", target_id=event.id,
        payload={"note": body.note},
    )
    db.commit()
    return ok(alerts.event_payload(event))


@router.post("/events/{event_id}/resolve")
def resolve(
    event_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    event = db.scalar(select(AlertEvent).where(
        AlertEvent.id == event_id, AlertEvent.project_id == ctx.project.id
    ))
    if event is None:
        raise AppError("预警事件不存在", code="alert_event_missing")
    event.status = ensure_alert_event_transition(
        event.status, AlertEventStatus.RESOLVED
    )
    db.flush()
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="alert.event.resolve", target_type="alert_event", target_id=event.id, payload={},
    )
    db.commit()
    return ok(alerts.event_payload(event))


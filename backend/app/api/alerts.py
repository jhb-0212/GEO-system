"""预警规则与事件 API。

读库与状态迁移都在 `services/alerts`：这里只做权限、审计、序列化，
api 层不留 select（架构闸门 `tests/test_architecture_guards.py` 第 2 条）。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, ok, ok_page
from app.db.session import get_db
from app.models.enums import AlertEventStatus, AlertRuleCode
from app.schemas import AlertEvaluateRequest, AlertEventAck, AlertRuleUpdate
from app.services import alerts
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
    rule = alerts.load_rule(db, ctx.project.id, rule_id)
    alerts.apply_rule_update(
        db,
        rule,
        is_enabled=body.is_enabled,
        severity=body.severity,
        thresholds=body.thresholds,
    )
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
    rows, total = alerts.page_events(
        db, ctx.project.id, status=status, code=code, page=page, page_size=page_size
    )
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
    event = alerts.require_event(db, ctx.project.id, event_id)
    alerts.acknowledge_event(db, event, actor_id=ctx.user.id, note=body.note)
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
    event = alerts.require_event(db, ctx.project.id, event_id)
    alerts.resolve_event(db, event)
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="alert.event.resolve", target_type="alert_event", target_id=event.id, payload={},
    )
    db.commit()
    return ok(alerts.event_payload(event))

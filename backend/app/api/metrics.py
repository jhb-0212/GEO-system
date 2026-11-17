"""指标口径：历史统计必须能追溯到当时使用的规则版本，每个 code 累积多个 rule_version。"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    MetricDefinitionCreated,
    MetricDefinitionData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import AppError, ResourceMissingError
from app.db.session import get_db
from app.models import MetricDefinition
from app.models.enums import MetricStatus
from app.schemas import MetricDefinitionCreate, MetricDefinitionUpdate
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/metric-definitions",
    tags=["指标口径"],
    responses=COMMON_ERRORS,
)


def _metric_data(metric: MetricDefinition) -> dict:
    return {
        "id": str(metric.id),
        "code": metric.code,
        "name": metric.name,
        "rule_version": metric.rule_version,
        "formula": metric.formula,
        "description": metric.description,
        "effective_from": metric.effective_from,
        "effective_to": metric.effective_to,
        "status": metric.status.value,
        "created_at": metric.created_at,
        "updated_at": metric.updated_at,
    }


def _next_rule_version(db: Session, project_id: uuid.UUID, code: str) -> int:
    current = (
        db.scalar(
            select(func.max(MetricDefinition.rule_version)).where(
                MetricDefinition.project_id == project_id,
                MetricDefinition.code == code,
            )
        )
        or 0
    )
    return current + 1


@router.get("", response_model=PagedEnvelope[MetricDefinitionData])
def list_metric_definitions(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    total = (
        db.scalar(
            select(func.count())
            .select_from(MetricDefinition)
            .where(MetricDefinition.project_id == ctx.project.id)
        )
        or 0
    )
    rows = db.scalars(
        select(MetricDefinition)
        .where(MetricDefinition.project_id == ctx.project.id)
        .order_by(MetricDefinition.code, MetricDefinition.rule_version.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [_metric_data(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[MetricDefinitionCreated])
def create_metric_definition(
    payload: MetricDefinitionCreate,
    ctx: ProjectContext = Depends(require_permission("metric.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """新增一条口径版本：同 code 的 rule_version 自增，默认立即生效。"""
    rule_version = _next_rule_version(db, ctx.project.id, payload.code)
    metric = MetricDefinition(
        project_id=ctx.project.id,
        code=payload.code,
        name=payload.name,
        rule_version=rule_version,
        formula=payload.formula,
        description=payload.description,
        effective_from=payload.effective_from or datetime.now(timezone.utc),
        status=MetricStatus.ACTIVE,
    )
    db.add(metric)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="metric.create",
        target_type="metric_definition",
        target_id=metric.id,
        payload={
            "code": metric.code,
            "rule_version": metric.rule_version,
            "name": metric.name,
        },
    )
    db.commit()
    return ok({"id": str(metric.id), "rule_version": metric.rule_version})


@router.patch("/{metric_id}", response_model=Envelope[MetricDefinitionData])
def update_metric_definition(
    metric_id: uuid.UUID,
    payload: MetricDefinitionUpdate,
    ctx: ProjectContext = Depends(require_permission("metric.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """局部更新：停用（retired）时自动落 effective_to，历史版本保留可追溯。"""
    metric = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.project_id == ctx.project.id,
            MetricDefinition.id == metric_id,
        )
    )
    if metric is None:
        raise ResourceMissingError("指标口径不存在", code="metric_missing")

    changes = payload.model_dump(exclude_unset=True)
    for field in ("name", "formula"):
        if field in changes and (
            changes[field] is None or not str(changes[field]).strip()
        ):
            raise AppError(f"{field} 不能为空", code="invalid_metric_field")

    if (
        "status" in changes
        and changes["status"] == MetricStatus.RETIRED
        and metric.status == MetricStatus.ACTIVE
        and metric.effective_to is None
    ):
        metric.effective_to = datetime.now(timezone.utc)

    audit_changes: dict[str, object] = {}
    for key, value in changes.items():
        setattr(metric, key, value)
        audit_changes[key] = value.value if hasattr(value, "value") else value

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="metric.update",
        target_type="metric_definition",
        target_id=metric.id,
        payload={"changes": audit_changes},
    )
    db.commit()
    return ok(_metric_data(metric))

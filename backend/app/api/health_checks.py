"""B5 体检接口：跑一次体检、回看历史快照。

权限沿用 `stats.read`：体检是读事实后汇总，不产生写业务数据的副作用，只有「留一份
体检快照」这一件事写库，故不要求 `stats.write`（系统里也没有这个码）。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.core.errors import AppError
from app.db.session import get_db
from app.services.queries import fetch_one
from app.models import HealthCheckRun
from app.services.audit import record_audit
from app.services.health_checks import list_runs, run_health_check, run_snapshot

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/health-checks",
    tags=["体检"],
    responses=COMMON_ERRORS,
)


@router.post("", response_model=Envelope[dict])
def create_run(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
) -> dict:
    snapshot = run_health_check(db, ctx.project.id, triggered_by=ctx.user.id)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="health_check.run",
        target_type="health_check_run",
        target_id=snapshot["run_id"],
        payload={"passed": snapshot["totals"]["passed"], "failed": snapshot["totals"]["failed"]},
    )
    db.commit()
    return ok(snapshot)


@router.get("", response_model=Envelope[list])
def list_history(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    return ok(list_runs(db, ctx.project.id, limit=limit))


@router.get("/{run_id}", response_model=Envelope[dict])
def get_run(
    run_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
) -> dict:
    run = fetch_one(
        db, HealthCheckRun, project_id=ctx.project.id, id=run_id
    )
    if run is None:
        raise AppError("体检记录不存在或不属于当前项目", code="health_run_not_found")
    return ok(run_snapshot(db, run))

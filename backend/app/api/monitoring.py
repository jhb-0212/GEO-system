"""监测接口：读数据要 monitoring.read，触发执行要 monitoring.execute。

执行限制：只有 pending 任务可触发；running 再点一次会被 409 挡住。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import ok
from app.core.errors import TaskRejectedError
from app.db.session import get_db
from app.models import MonitoringTask
from app.models.enums import TaskStatus
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(prefix="/api/v1/projects/{project_id}/monitoring", tags=["监测"])


@router.get("/tasks")
def list_tasks(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    round_id: uuid.UUID | None = None,
    status: TaskStatus | None = None,
) -> dict:
    query = select(MonitoringTask).where(MonitoringTask.project_id == ctx.project.id)
    if round_id is not None:
        query = query.where(MonitoringTask.round_id == round_id)
    if status is not None:
        query = query.where(MonitoringTask.status == status)

    rows = db.scalars(query.order_by(MonitoringTask.created_at.desc()).limit(200)).all()
    return ok(
        [
            {
                "id": str(row.id),
                "round_id": str(row.round_id),
                "status": row.status,
                "sampling_no": row.sampling_no,
            }
            for row in rows
        ]
    )


@router.post("/tasks/{task_id}/execute", status_code=202)
def execute_task(
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    task = require_scoped_row(
        db, MonitoringTask, ctx.project.id, resource="monitoring_task", id=task_id
    )
    if task.status != TaskStatus.PENDING:
        raise TaskRejectedError(f"仅 pending 任务可触发，当前状态 {task.status}")

    task.status = TaskStatus.RUNNING
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="monitoring.execute",
        target_type="monitoring_task",
        target_id=task.id,
        payload={"from": TaskStatus.PENDING.value, "to": TaskStatus.RUNNING.value},
    )
    db.commit()
    return ok({"task_id": str(task.id), "status": task.status})

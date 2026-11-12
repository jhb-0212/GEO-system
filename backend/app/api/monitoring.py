"""监测接口：读数据要 monitoring.read，触发执行要 monitoring.execute。

执行限制：只有 pending 任务可触发；running 再点一次会被 409 挡住。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    MonitoringExecuted,
    MonitoringTaskData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import TaskRejectedError
from app.db.session import get_db
from app.models import MonitoringTask
from app.models.enums import TaskStatus
from app.services.audit import record_audit
from app.services.outbox import emit_event
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/monitoring",
    tags=["监测"],
    responses=COMMON_ERRORS,
)


@router.get("/tasks", response_model=PagedEnvelope[MonitoringTaskData])
def list_tasks(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    round_id: uuid.UUID | None = None,
    status: TaskStatus | None = None,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    filters = [MonitoringTask.project_id == ctx.project.id]
    if round_id is not None:
        filters.append(MonitoringTask.round_id == round_id)
    if status is not None:
        filters.append(MonitoringTask.status == status)

    total = db.scalar(select(func.count()).select_from(MonitoringTask).where(*filters)) or 0
    rows = db.scalars(
        select(MonitoringTask)
        .where(*filters)
        .order_by(MonitoringTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(row.id),
                "round_id": str(row.round_id),
                "status": row.status,
                "sampling_no": row.sampling_no,
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/tasks/{task_id}/execute",
    status_code=202,
    response_model=Envelope[MonitoringExecuted],
)
def execute_task(
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    task = require_scoped_row(
        db, MonitoringTask, ctx.project.id, resource="monitoring_task", id=task_id
    )

    # 原子条件更新：只有仍为 pending 的行会被抢到，避免并发请求同时读到 pending
    # 后都改成 running、重复写审计。
    result = db.execute(
        update(MonitoringTask)
        .where(
            MonitoringTask.id == task.id,
            MonitoringTask.project_id == ctx.project.id,
            MonitoringTask.status == TaskStatus.PENDING,
        )
        .values(status=TaskStatus.RUNNING)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise TaskRejectedError("仅 pending 任务可触发，任务已被其他请求占用或状态不允许")

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="monitoring.execute",
        target_type="monitoring_task",
        target_id=task.id,
        payload={"from": TaskStatus.PENDING.value, "to": TaskStatus.RUNNING.value},
    )
    # 状态与事件同事务：只有提交成功，outbox dispatcher 才看得到这条事件。
    emit_event(
        db,
        project_id=ctx.project.id,
        topic="monitoring.task.execute",
        payload={
            "project_id": str(ctx.project.id),
            "task_id": str(task.id),
            "round_id": str(task.round_id),
        },
    )
    db.commit()
    return ok({"task_id": str(task.id), "status": TaskStatus.RUNNING.value})

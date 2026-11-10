"""发布接口：读要 publish.read，记录发布尝试要 publish.execute。

状态机（API 层强制）：只有 pending / needs_review 能新增 attempt；
unknown 必须先核实，publishing 禁止重复提交，published 是终态。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import ok
from app.core.errors import TaskRejectedError
from app.db.session import get_db
from app.models import PublishAttempt, PublishTask
from app.models.enums import AttemptResult, PublishTaskStatus
from app.schemas import PublishAttemptCreate
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(prefix="/api/v1/projects/{project_id}/publish", tags=["发布"])

ATTEMPT_ALLOWED_STATUSES = {PublishTaskStatus.PENDING, PublishTaskStatus.NEEDS_REVIEW}


@router.get("/tasks")
def list_tasks(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
    status: PublishTaskStatus | None = None,
) -> dict:
    query = select(PublishTask).where(PublishTask.project_id == ctx.project.id)
    if status is not None:
        query = query.where(PublishTask.status == status)

    rows = db.scalars(query.order_by(PublishTask.created_at.desc()).limit(200)).all()
    return ok(
        [
            {
                "id": str(row.id),
                "status": row.status,
                "channel_id": str(row.channel_id),
                "version_id": str(row.version_id),
            }
            for row in rows
        ]
    )


@router.post("/tasks/{task_id}/attempts", status_code=201)
def create_attempt(
    task_id: uuid.UUID,
    payload: PublishAttemptCreate,
    ctx: ProjectContext = Depends(require_permission("publish.execute")),
    db: Session = Depends(get_db),
) -> dict:
    task = require_scoped_row(db, PublishTask, ctx.project.id, resource="publish_task", id=task_id)

    if task.status == PublishTaskStatus.UNKNOWN:
        raise TaskRejectedError("发布状态为 unknown，必须先核实回执，禁止直接新增尝试")
    if task.status == PublishTaskStatus.PUBLISHING:
        raise TaskRejectedError("正在发布中，禁止重复提交")
    if task.status == PublishTaskStatus.PUBLISHED:
        raise TaskRejectedError("已发布为终态，不能再新增尝试")
    if task.status not in ATTEMPT_ALLOWED_STATUSES:
        raise TaskRejectedError(f"当前状态 {task.status} 不允许新增尝试")

    previous_max = db.scalar(
        select(func.max(PublishAttempt.attempt_no)).where(PublishAttempt.task_id == task.id)
    )
    attempt_no = (previous_max or 0) + 1
    now = datetime.now(timezone.utc)
    attempt = PublishAttempt(
        project_id=ctx.project.id,
        task_id=task.id,
        attempt_no=attempt_no,
        mode=payload.mode,
        result=payload.result,
        started_at=now,
        finished_at=now,
        error_code=payload.error_code,
        error_note=payload.error_note,
        operator_id=ctx.user.id,
    )
    db.add(attempt)
    task.status = (
        PublishTaskStatus.PUBLISHING
        if payload.result == AttemptResult.SUCCESS
        else PublishTaskStatus.FAILED
    )
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="publish.attempt",
        target_type="publish_task",
        target_id=task.id,
        payload={"attempt_no": attempt_no, "result": payload.result.value, "task_status": task.status.value},
    )
    db.commit()
    return ok({"attempt_id": str(attempt.id), "attempt_no": attempt_no, "task_status": task.status})

"""统一任务状态查询：任务所属项目的成员才能查，跨项目一律 403 project_forbidden。

状态来源是 outbox_events（业务动作与事件同事务落库）；任务状态不代表业务状态，
业务状态以 monitoring_samples / publish_tasks 等资源记录为准。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.responses import COMMON_ERRORS, Envelope, TaskStatusData, ok
from app.core.errors import ResourceMissingError
from app.db.session import get_db
from app.models import OutboxEvent, User
from app.services.access import ensure_capability, resolve_project_context

router = APIRouter(prefix="/api/v1/tasks", tags=["任务状态"], responses=COMMON_ERRORS)


@router.get("/{task_id}", response_model=Envelope[TaskStatusData])
def get_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    event = db.get(OutboxEvent, task_id)
    if event is None:
        raise ResourceMissingError("任务不存在", code="task_missing")

    # 按任务所属项目重新解析授权，跨项目访问在这里被 403 挡下
    ctx = resolve_project_context(db, event.project_id, user)
    ensure_capability(db, ctx, "project.read")

    return ok(
        {
            "task_id": str(event.id),
            # 契约 1.5 的 kind：把 outbox topic 归一为执行器类型
            "kind": event.topic.replace(".task", ""),
            "project_id": str(event.project_id) if event.project_id else None,
            "topic": event.topic,
            "status": event.status,
            # progress / finished_at 当前无数据源，显式返回 null，不伪造数值
            "progress": None,
            "error": event.error_note,
            "finished_at": None,
            "created_at": event.created_at,
            "dispatched_at": event.dispatched_at,
        }
    )

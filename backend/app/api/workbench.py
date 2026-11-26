"""工作台待办聚合接口：六类待办项目级计数与预览的唯一入口。"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_any_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.db.session import get_db
from app.services.workbench_todos import todo_snapshot

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/workbench",
    tags=["工作台"],
    responses=COMMON_ERRORS,
)


@router.get("/todos", response_model=Envelope[dict])
def get_workbench_todos(
    ctx: ProjectContext = Depends(
        require_any_permission("content.read", "publish.read", "monitoring.read")
    ),
    db: Session = Depends(get_db),
    range_value: Literal["today", "week", "all"] = Query(
        default="all",
        alias="range",
        description="按进入当前待处理状态的时间筛选：today / week / all",
    ),
    tz_offset_minutes: int = Query(
        default=480,
        ge=-720,
        le=840,
        description="调用方本地时区相对 UTC 的分钟偏移，用于计算今天/本周边界",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=50,
        description="每个分组最多返回的预览条数；计数始终为全量",
    ),
) -> dict:
    return ok(
        todo_snapshot(
            db,
            ctx.project.id,
            range_value=range_value,
            tz_offset_minutes=tz_offset_minutes,
            limit=limit,
            permissions=ctx.permissions,
        )
    )

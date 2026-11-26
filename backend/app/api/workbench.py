"""工作台待办聚合接口：六类待办项目级计数与预览的唯一入口。"""

import hashlib
import hmac
import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_any_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.core.config import settings
from app.core.errors import BusinessValidationError
from app.db.session import get_db
from app.services.time_windows import ProjectCalendar, ProjectTimezoneInvalid, project_calendar
from app.services.workbench_todos import todo_snapshot

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/workbench",
    tags=["工作台"],
    responses=COMMON_ERRORS,
)

logger = logging.getLogger("geo.workbench")


def _project_utc_offset_minutes(calendar: ProjectCalendar) -> int:
    offset = calendar.now.astimezone(calendar.zone).utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0


def _project_hmac(project_id) -> str:
    """带密钥的短摘要，只用于聚合观测，不可由外部枚举反推。"""
    digest = hmac.new(
        settings.secret_key.encode("utf-8"), str(project_id).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return digest[:16]


def _log_timezone_param(project, calendar: ProjectCalendar, param_value: int | None) -> None:
    """旧偏移参数的调用量观测：只记录非敏感聚合字段，不写请求头/身份/请求体。"""
    logger.info(
        "workbench_todos_tz_param %s",
        json.dumps(
            {
                "route": "GET /api/v1/projects/{project_id}/workbench/todos",
                "env": settings.app_env,
                "app_version": settings.app_version,
                "release_sha": settings.release_sha,
                "param_present": param_value is not None,
                "param_value": param_value,
                "project_utc_offset_minutes": _project_utc_offset_minutes(calendar),
                "project_hmac": _project_hmac(project.id),
                "business_timezone": calendar.zone.key,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
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
    tz_offset_minutes: int | None = Query(
        default=None,
        ge=-720,
        le=840,
        deprecated=True,
        description="兼容参数，已忽略；今天/本周一律按项目业务时区（Project.timezone）计算",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=50,
        description="每个分组最多返回的预览条数；计数始终为全量",
    ),
) -> dict:
    try:
        calendar = project_calendar(ctx.project)
    except ProjectTimezoneInvalid as exc:
        raise BusinessValidationError("项目时区配置无效，无法计算业务窗口", code="project_timezone_invalid") from exc

    _log_timezone_param(ctx.project, calendar, tz_offset_minutes)
    return ok(
        todo_snapshot(
            db,
            ctx.project.id,
            range_value=range_value,
            limit=limit,
            permissions=ctx.permissions,
            now=calendar.now,
        )
    )

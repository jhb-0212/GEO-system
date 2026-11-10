"""Celery 任务参数校验：Worker 执行前二次确认项目归属与状态。

API 进程里的授权不代表 Worker 可以信任消息体，队列里的 project_id 必须重新落库核对。
"""

import functools
import uuid
from collections.abc import Callable
from typing import Any

from app.core.errors import TaskRejectedError
from app.db.session import SessionLocal
from app.models import Project
from app.models.enums import ProjectStatus


def ensure_task_project(project_id: str | uuid.UUID | None) -> uuid.UUID:
    """校验任务参数里的 project_id：格式合法、项目存在、项目处于启用状态。"""
    if project_id is None:
        raise TaskRejectedError("task requires project_id")
    try:
        pid = uuid.UUID(str(project_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise TaskRejectedError("invalid project_id") from exc

    with SessionLocal() as db:
        project = db.get(Project, pid)
        if project is None:
            raise TaskRejectedError("project not found")
        if project.status != ProjectStatus.ACTIVE:
            raise TaskRejectedError("project is not active")
    return pid


def project_guarded(func: Callable[..., Any]) -> Callable[..., Any]:
    """任务装饰器：要求 kwargs 带 project_id，执行前校验，并把规范化后的值回传。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        pid = ensure_task_project(kwargs.get("project_id"))
        kwargs["project_id"] = str(pid)
        return func(*args, **kwargs)

    return wrapper

"""后台任务参数校验测试：队列消息里的项目标识必须重新落库核对。"""

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import TaskRejectedError
from app.core.task_guard import ensure_task_project
from app.db.session import SessionLocal
from app.models import Project


def test_missing_project_id_is_rejected():
    with pytest.raises(TaskRejectedError):
        ensure_task_project(None)


def test_malformed_project_id_is_rejected():
    with pytest.raises(TaskRejectedError):
        ensure_task_project("not-a-uuid")


def test_unknown_project_is_rejected():
    with pytest.raises(TaskRejectedError):
        ensure_task_project(uuid.uuid4())


def test_active_project_is_accepted():
    """用 seed 里已提交的 gz-base 项目验证通过路径（Worker 走独立会话，只认已提交数据）。"""
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == "gz-base"))
    assert project is not None, "gz-base 项目缺失，先跑 backend/scripts/seed.py"
    assert ensure_task_project(str(project.id)) == project.id

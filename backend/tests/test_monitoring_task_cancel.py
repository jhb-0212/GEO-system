"""监测任务作废：只允许 pending，保留任务记录并写审计，不做物理删除。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    AuditLog,
    MonitoringRound,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    EngineEntryType,
    QuestionStatus,
    QuestionType,
    RoleCode,
    RoundStatus,
    TaskStatus,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _task_fixture(db, project, *, status: TaskStatus, suffix: str) -> MonitoringTask:
    engine = AiEngine(
        code=f"cancel-engine-{suffix}",
        name="作废测试引擎",
        vendor="测试",
        supports_search=True,
        supports_citation=False,
        is_active=True,
    )
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        entry_type=EngineEntryType.WEB_USER,
        name=f"作废网页端-{suffix}",
        supports_search=True,
        is_active=True,
    )
    db.add(entry)
    db.flush()
    question = Question(
        project_id=project.id,
        code=f"cancel-q-{suffix}",
        title="作废测试问题",
        question_type=QuestionType.GENERAL,
        audience="零基础转行者",
        intent="了解课程",
        priority=100,
        status=QuestionStatus.ACTIVE,
        current_version_no=1,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text="作废测试问题正文",
    )
    db.add(version)
    db.flush()
    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="作废测试轮次",
        status=RoundStatus.PLANNING,
    )
    db.add(round_row)
    db.flush()
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        status=status,
        trace_id=uuid.uuid4().hex,
    )
    db.add(task)
    db.flush()
    return task


def test_cancel_pending_task_keeps_record_and_audits(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"task-cancel-{suffix}")
    editor = user_factory(f"task-cancel-editor-{suffix}")
    viewer = user_factory(f"task-cancel-viewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, viewer, RoleCode.VIEWER)
    task = _task_fixture(db, project, status=TaskStatus.PENDING, suffix=suffix)

    denied = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{task.id}/cancel",
        headers=_auth(viewer),
    )
    assert denied.status_code == 403

    response = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{task.id}/cancel",
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "task_id": str(task.id),
        "status": TaskStatus.CANCELLED.value,
    }
    db.refresh(task)
    assert task.status == TaskStatus.CANCELLED
    assert task.lease_owner is None
    assert db.get(MonitoringTask, task.id) is not None

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.target_id == task.id,
            AuditLog.action == "monitoring.task_cancel",
        )
    )
    assert audit is not None
    assert audit.payload["serial_no"] == task.serial_no
    assert audit.payload["from"] == TaskStatus.PENDING.value
    assert audit.payload["to"] == TaskStatus.CANCELLED.value

    repeated = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{task.id}/cancel",
        headers=_auth(editor),
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "task_rejected"


def test_project_admin_can_cancel_pending_task(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"task-cancel-admin-{suffix}")
    admin = user_factory(f"task-cancel-admin-user-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    task = _task_fixture(db, project, status=TaskStatus.PENDING, suffix=suffix)

    response = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{task.id}/cancel",
        headers=_auth(admin),
    )
    assert response.status_code == 200, response.text
    db.refresh(task)
    assert task.status == TaskStatus.CANCELLED


def test_cancel_running_task_is_rejected(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"task-running-{suffix}")
    editor = user_factory(f"task-running-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    task = _task_fixture(db, project, status=TaskStatus.RUNNING, suffix=suffix)

    response = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{task.id}/cancel",
        headers=_auth(editor),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "task_rejected"
    db.refresh(task)
    assert task.status == TaskStatus.RUNNING

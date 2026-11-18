"""轮次完成自动冻结统计快照回归。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update

from app.core.security import create_access_token
from app.models import AiEngine, AiEngineEntry, MonitoringTask, Question, QuestionVersion
from app.models.enums import EngineEntryType, QuestionStatus, QuestionType, RoleCode, TaskStatus


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _prepare_project_question(db, project) -> None:
    suffix = uuid.uuid4().hex[:6]
    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="轮次完成测试题",
        question_type=QuestionType.GENERAL,
        status=QuestionStatus.ACTIVE,
    )
    engine = AiEngine(
        code=f"e-{suffix}",
        name="轮次完成引擎",
        vendor="测试",
        supports_search=True,
    )
    db.add_all([question, engine])
    db.flush()
    db.add(
        QuestionVersion(
            project_id=project.id,
            question_id=question.id,
            version_no=1,
            text=question.title,
        )
    )
    entry = AiEngineEntry(
        engine_id=engine.id,
        name="网页端",
        entry_type=EngineEntryType.WEB_USER,
        is_active=True,
    )
    db.add(entry)
    db.flush()


def _create_round(client, project, editor, *, name: str) -> str:
    response = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds",
        json={"name": name, "is_baseline": False},
        headers=_auth(editor),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _generate(client, project, editor, round_id: str):
    return client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        headers=_auth(editor),
    )


def _round_status(client, project, editor, round_id: str) -> str:
    response = client.get(
        f"/api/v1/projects/{project.id}/monitoring/rounds", headers=_auth(editor)
    )
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["data"] if item["id"] == round_id)
    return row["status"]


def test_generate_starts_round_and_completion_freezes_snapshot(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"round-complete-{suffix}")
    editor = user_factory(f"round-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    _prepare_project_question(db, project)

    round_id = _create_round(client, project, editor, name="自动冻结轮次")
    assert _round_status(client, project, editor, round_id) == "planning"

    generated = _generate(client, project, editor, round_id)
    assert generated.status_code == 200, generated.text
    assert generated.json()["data"]["generated_task_count"] >= 1
    assert _round_status(client, project, editor, round_id) == "running"

    task_count = db.scalar(
        select(func.count())
        .select_from(MonitoringTask)
        .where(
            MonitoringTask.project_id == project.id,
            MonitoringTask.round_id == uuid.UUID(round_id),
        )
    )
    assert task_count
    db.execute(
        update(MonitoringTask)
        .where(
            MonitoringTask.project_id == project.id,
            MonitoringTask.round_id == uuid.UUID(round_id),
        )
        .values(status=TaskStatus.DONE)
    )
    db.commit()

    completed = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/complete",
        headers=_auth(editor),
    )
    assert completed.status_code == 200, completed.text
    data = completed.json()["data"]
    assert data["round"]["status"] == "completed"
    assert data["task_counts"] == {"done": task_count}
    assert data["snapshot_hash"]

    snapshot = client.get(
        f"/api/v1/projects/{project.id}/stats/snapshots/{data['snapshot_id']}",
        headers=_auth(editor),
    )
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["data"]["scope"]["round"]["status"] == "completed"

    repeated = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/complete",
        headers=_auth(editor),
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["data"]["snapshot_id"] == data["snapshot_id"]

    blocked_generate = _generate(client, project, editor, round_id)
    assert blocked_generate.status_code == 409, blocked_generate.text
    assert blocked_generate.json()["error"]["code"] == "round_not_open"


def test_completion_rejects_unfinished_tasks(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"round-pending-{suffix}")
    editor = user_factory(f"round-pending-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    _prepare_project_question(db, project)

    round_id = _create_round(client, project, editor, name="未完成轮次")
    generated = _generate(client, project, editor, round_id)
    assert generated.status_code == 200, generated.text
    assert generated.json()["data"]["generated_task_count"] >= 1

    blocked = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/complete",
        headers=_auth(editor),
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "round_tasks_unfinished"

    started = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/start",
        headers=_auth(editor),
    )
    assert started.status_code == 200, started.text
    assert started.json()["data"]["status"] == "running"


def test_completion_rejects_round_without_tasks(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"round-empty-{suffix}")
    editor = user_factory(f"round-empty-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    round_id = _create_round(client, project, editor, name="空轮次")
    started = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/start",
        headers=_auth(editor),
    )
    assert started.status_code == 200, started.text
    assert started.json()["data"]["status"] == "running"

    blocked = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/complete",
        headers=_auth(editor),
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "round_no_tasks"

"""B4 监测轮次 + “启用题目 × 启用平台”批量生成测试。

覆盖：建轮次权限与 seq 规则、基线幂等、动态基线生成、重放幂等、未激活题目排除、
版本缺失/引擎入口不足分支、跨项目越权、审计留痕、采样器失败落库与终态回写。
"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    AuditLog,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    EngineEntryType,
    FailureCode,
    QuestionStatus,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    TaskStatus,
)
from app.services.monitoring_collection import plan_round_tasks, run_pending_tasks


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _seed_engine(db, suffix: str, code: str) -> tuple[AiEngine, AiEngineEntry]:
    engine = AiEngine(
        code=f"{code}-{suffix}",
        name=f"引擎-{code}",
        vendor="测试",
        supports_search=True,
        supports_citation=True,
        is_active=True,
    )
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        entry_type=EngineEntryType.WEB_USER,
        name=f"网页端-{code}",
        supports_search=True,
        is_active=True,
    )
    db.add(entry)
    db.flush()
    return engine, entry


def _seed_question(
    db,
    project,
    code: str,
    *,
    status: QuestionStatus = QuestionStatus.ACTIVE,
    with_version: bool = True,
) -> tuple[Question, QuestionVersion | None]:
    question = Question(
        project_id=project.id,
        code=code,
        title=f"问题 {code}",
        question_type=QuestionType.GENERAL,
        audience="零基础转行者",
        intent="了解课程",
        priority=100,
        status=status,
        current_version_no=1,
    )
    db.add(question)
    db.flush()
    version = None
    if with_version:
        version = QuestionVersion(
            project_id=project.id,
            question_id=question.id,
            version_no=1,
            text=f"正文 {code}",
        )
        db.add(version)
        db.flush()
    return question, version


def _create_round(client, project, user, *, is_baseline: bool = False) -> str:
    resp = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds",
        json={"is_baseline": is_baseline},
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


def test_create_round_editor_ok_and_seq_increments(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r1-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    viewer = user_factory(f"vw-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)

    url = f"/api/v1/projects/{project.id}/monitoring/rounds"
    r1 = client.post(url, json={"is_baseline": False}, headers=_auth(editor))
    assert r1.status_code == 201
    assert r1.json()["data"]["seq"] == 1

    r2 = client.post(url, json={"is_baseline": False}, headers=_auth(editor))
    assert r2.status_code == 201
    assert r2.json()["data"]["seq"] == 2

    denied = client.post(url, json={"is_baseline": False}, headers=_auth(viewer))
    assert denied.status_code == 403


def test_baseline_idempotent(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r2-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    url = f"/api/v1/projects/{project.id}/monitoring/rounds"

    r1 = client.post(url, json={"is_baseline": True}, headers=_auth(editor))
    r2 = client.post(url, json={"is_baseline": True}, headers=_auth(editor))
    assert r1.json()["data"]["id"] == r2.json()["data"]["id"]

    rounds = db.scalars(select(MonitoringRound).where(MonitoringRound.project_id == project.id)).all()
    assert len(rounds) == 1
    assert rounds[0].is_baseline is True


def test_baseline_after_non_baseline_takes_next_seq(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r3-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    url = f"/api/v1/projects/{project.id}/monitoring/rounds"

    r1 = client.post(url, json={"is_baseline": False}, headers=_auth(editor))
    r2 = client.post(url, json={"is_baseline": True}, headers=_auth(editor))
    assert r1.json()["data"]["seq"] == 1
    assert r2.json()["data"]["seq"] == 2
    assert r2.json()["data"]["is_baseline"] is True

    first = db.get(MonitoringRound, uuid.UUID(r1.json()["data"]["id"]))
    assert first.is_baseline is False


def _reset_existing_engines(db) -> None:
    """停用库内既有引擎/入口（仅本事务，结束回滚），保证引擎数由本测试夹具决定。"""
    for entry in db.scalars(select(AiEngineEntry)).all():
        entry.is_active = False
    for engine in db.scalars(select(AiEngine)).all():
        engine.is_active = False
    db.flush()


def _seed_full_project(db, project, *, question_count: int = 6, engine_count: int = 4) -> str:
    suffix = uuid.uuid4().hex[:6]
    for index in range(1, engine_count + 1):
        _seed_engine(db, suffix, f"E{index}")
    for index in range(1, question_count + 1):
        _seed_question(db, project, f"Q{index:02d}")
    return suffix


def test_batch_full_six_by_four(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r4-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    _seed_full_project(db, project)

    round_id = _create_round(client, project, editor)
    resp = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        headers=_auth(editor),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["engine_count"] == 4
    assert data["expected_engine_count"] == 4
    assert data["requested_question_count"] == 6
    assert data["eligible_question_count"] == 6
    assert data["expected_question_count"] == 6
    assert data["expected_task_count"] == 24
    assert data["created_task_count"] == 24
    assert data["reused_task_count"] == 0
    assert data["generated_task_count"] == 24
    assert data["complete"] is True
    assert data["skipped_reason"] is None

    listed = client.get(
        f"/api/v1/projects/{project.id}/monitoring/tasks?round_id={round_id}",
        headers=_auth(editor),
    )
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 24
    first = listed.json()["data"][0]
    assert first["question_code"].startswith("Q")
    assert first["question_title"].startswith("问题 ")
    assert first["engine_code"].startswith("E")
    assert first["engine_name"].startswith("引擎-")
    assert first["entry_name"]
    assert first["entry_type"]
    assert first["created_at"] and first["updated_at"]


def test_batch_accepts_entry_types_multi_entry_per_engine(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r4b-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    suffix = _seed_full_project(db, project)
    for engine in db.scalars(select(AiEngine).where(AiEngine.code.like(f"%-{suffix}"))).all():
        db.add(
            AiEngineEntry(
                engine_id=engine.id,
                entry_type=EngineEntryType.API,
                name=f"API-{engine.code}",
                supports_search=True,
                is_active=True,
            )
        )
    db.flush()

    round_id = _create_round(client, project, editor)
    resp = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        json={"entry_types": ["web_user", "api"]},
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["engine_count"] == 4
    assert data["engine_entry_count"] == 8
    assert data["missing_engine_entry_count"] == 0
    assert data["expected_engine_entry_count"] == 8
    assert data["requested_entry_types"] == ["api", "web_user"]
    assert data["expected_task_count"] == 48
    assert data["created_task_count"] == 48
    assert data["generated_task_count"] == 48
    assert data["complete"] is True
    assert data["skipped_reason"] is None

    replay = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        json={"entry_types": ["api", "web_user"]},
        headers=_auth(editor),
    ).json()["data"]
    assert replay["created_task_count"] == 0
    assert replay["reused_task_count"] == 48
    assert replay["generated_task_count"] == 48


def test_batch_replay_is_idempotent(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r5-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    _seed_full_project(db, project)

    round_id = _create_round(client, project, editor)
    batch_url = f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch"
    first = client.post(batch_url, headers=_auth(editor)).json()["data"]
    second = client.post(batch_url, headers=_auth(editor)).json()["data"]

    assert first["created_task_count"] == 24
    assert second["created_task_count"] == 0
    assert second["reused_task_count"] == 24
    assert second["generated_task_count"] == 24
    assert second["complete"] is True


def test_batch_supports_multiple_samples_per_cell(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"r5b-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    _seed_full_project(db, project)

    round_id = _create_round(client, project, editor)
    data = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        json={"samples_per_cell": 3},
        headers=_auth(editor),
    ).json()["data"]
    assert data["samples_per_cell"] == 3
    assert data["expected_task_count"] == 72
    assert data["created_task_count"] == 72
    assert data["complete"] is True

    tasks = db.scalars(
        select(MonitoringTask).where(MonitoringTask.round_id == uuid.UUID(round_id))
    ).all()
    assert len(tasks) == 72
    assert {task.sampling_no for task in tasks} == {1, 2, 3}


def test_batch_excludes_entries_without_search(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"r5c-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    suffix = _seed_full_project(db, project)
    entry = db.scalar(
        select(AiEngineEntry)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(
            AiEngine.code == f"E4-{suffix}",
            AiEngineEntry.name == "网页端-E4",
        )
    )
    assert entry is not None
    entry.supports_search = False
    db.flush()

    round_id = _create_round(client, project, editor)
    data = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        headers=_auth(editor),
    ).json()["data"]
    assert data["engine_count"] == 3
    assert data["engine_entry_count"] == 3
    assert data["missing_engine_entry_count"] == 1
    assert data["expected_task_count"] == 18
    assert data["complete"] is False
    assert data["skipped_reason"] == "engine_entries_insufficient"


def test_batch_inactive_questions_are_reported(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r6-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    suffix = uuid.uuid4().hex[:6]
    for index in range(1, 5):
        _seed_engine(db, suffix, f"E{index}")
    for index in range(1, 5):
        _seed_question(db, project, f"Q{index:02d}", status=QuestionStatus.ACTIVE)
    for index in range(5, 7):
        _seed_question(db, project, f"Q{index:02d}", status=QuestionStatus.DRAFT)

    round_id = _create_round(client, project, editor)
    data = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        headers=_auth(editor),
    ).json()["data"]

    assert data["eligible_question_count"] == 4
    assert data["expected_question_count"] == 4
    assert data["inactive_question_count"] == 2
    assert data["expected_task_count"] == 16
    assert data["created_task_count"] == 16
    assert data["complete"] is True
    assert data["skipped_reason"] is None
    assert [q["code"] for q in data["inactive_questions"]] == ["Q05", "Q06"]


def test_batch_no_active_question_is_incomplete(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r6b-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    suffix = uuid.uuid4().hex[:6]
    for index in range(1, 5):
        _seed_engine(db, suffix, f"E{index}")
    for index in range(1, 3):
        _seed_question(db, project, f"Q{index:02d}", status=QuestionStatus.DRAFT)

    round_id = _create_round(client, project, editor)
    data = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        headers=_auth(editor),
    ).json()["data"]

    assert data["eligible_question_count"] == 0
    assert data["requested_question_count"] == 2
    assert data["expected_task_count"] == 0
    assert data["created_task_count"] == 0
    assert data["complete"] is False
    assert data["skipped_reason"] == "no_active_question"


def test_batch_version_missing_blocks(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r7-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    _seed_full_project(db, project)
    # 覆盖一道 active 但缺当前版本的题
    _seed_question(db, project, "Q07", with_version=False)

    round_id = _create_round(client, project, editor)
    data = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        headers=_auth(editor),
    ).json()["data"]

    assert data["question_version_missing_count"] == 1
    assert data["complete"] is False
    assert data["skipped_reason"] == "question_version_missing"
    # 整批阻断：版本缺失时不生成任何任务（created/reused/generated 均为 0）
    assert data["created_task_count"] == 0
    assert data["reused_task_count"] == 0
    assert data["generated_task_count"] == 0


def test_batch_three_engines_expands_baseline_to_eighteen(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r8-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    _seed_full_project(db, project, engine_count=3)

    round_id = _create_round(client, project, editor)
    data = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        headers=_auth(editor),
    ).json()["data"]

    assert data["engine_count"] == 3
    assert data["expected_engine_count"] == 3
    assert data["expected_task_count"] == 18
    assert data["generated_task_count"] == 18
    assert data["complete"] is True
    assert data["skipped_reason"] is None


def test_batch_engine_count_above_four_expands_baseline(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r8b-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    _seed_full_project(db, project, engine_count=5)

    round_id = _create_round(client, project, editor)
    data = client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        headers=_auth(editor),
    ).json()["data"]

    assert data["engine_count"] == 5
    assert data["expected_engine_count"] == 5
    assert data["expected_task_count"] == 30
    assert data["generated_task_count"] == 30
    assert data["complete"] is True
    assert data["skipped_reason"] is None


def test_list_rounds_baseline_first_then_seq_desc(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"r11-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    viewer = user_factory(f"vw-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)

    _create_round(client, project, editor, is_baseline=False)
    _create_round(client, project, editor, is_baseline=True)
    url = f"/api/v1/projects/{project.id}/monitoring/rounds"

    resp = client.get(url, headers=_auth(editor))
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 2
    # 排序：先 is_baseline DESC（基线置顶），再 seq DESC
    assert [row["is_baseline"] for row in body["data"]] == [True, False]
    assert [row["seq"] for row in body["data"]] == [2, 1]

    page = client.get(url, params={"page": 1, "page_size": 1}, headers=_auth(viewer))
    assert page.status_code == 200
    assert len(page.json()["data"]) == 1
    assert page.json()["meta"]["total"] == 2


def test_batch_rejects_cross_project_access(client, db, two_projects, user_factory, member_factory):
    p1, p2 = two_projects
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(p1, editor, RoleCode.EDITOR)
    outsider = user_factory(f"out-{uuid.uuid4().hex[:6]}")
    member_factory(p2, outsider, RoleCode.EDITOR)

    round_id = _create_round(client, p1, editor)
    resp = client.post(
        f"/api/v1/projects/{p1.id}/monitoring/rounds/{round_id}/tasks/batch",
        headers=_auth(outsider),
    )
    assert resp.status_code == 403


def test_batch_writes_audit(db, client, project_factory, user_factory, member_factory):
    project = project_factory(f"r9-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _reset_existing_engines(db)
    _seed_full_project(db, project)

    round_id = _create_round(client, project, editor)
    client.post(
        f"/api/v1/projects/{project.id}/monitoring/rounds/{round_id}/tasks/batch",
        headers=_auth(editor),
    )

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "monitoring.tasks_batch_generate",
            AuditLog.project_id == project.id,
        )
    )
    assert audit is not None
    assert audit.payload["generated_task_count"] == 24
    assert audit.payload["complete"] is True


def test_sampler_writes_failed_sample_and_marks_task_failed(db, project_factory):
    project = project_factory(f"r10-{uuid.uuid4().hex[:6]}")
    _, entry = _seed_engine(db, uuid.uuid4().hex[:6], "E1")
    _, version = _seed_question(db, project, "Q01")

    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="基线轮次",
        is_baseline=True,
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
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()

    result = run_pending_tasks(db, project_id=project.id)
    assert result["task_count"] == 1
    assert result["executed_count"] == 1
    assert result["failed_count"] == 1

    db.refresh(task)
    assert task.status == TaskStatus.FAILED

    sample = db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task.id))
    assert sample is not None
    assert sample.status == SampleStatus.FAILED
    assert sample.failure_code == FailureCode.ACCESS_BLOCKED
    assert sample.failure_note
    # failed 任务必须有带 failure_code 的 failed 样本（DB 层无 CHECK，靠服务与测试兜）
    assert sample.failure_code is not None


def test_plan_round_skips_round_with_manual_app_search_tasks(db, project_factory):
    project = project_factory(f"r11-{uuid.uuid4().hex[:6]}")
    _, entry = _seed_engine(db, uuid.uuid4().hex[:6], "APP")
    entry.entry_type = EngineEntryType.APP_SEARCH
    entry.is_active = False
    _, version = _seed_question(db, project, "Q01")
    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="应用内人工轮次",
        is_baseline=False,
        status=RoundStatus.RUNNING,
    )
    db.add(round_row)
    db.flush()
    db.add(
        MonitoringTask(
            project_id=project.id,
            round_id=round_row.id,
            question_version_id=version.id,
            engine_entry_id=entry.id,
            sampling_no=1,
            status=TaskStatus.PENDING,
        )
    )
    db.flush()

    result = plan_round_tasks(db, project_id=project.id, round_id=round_row.id)
    assert result["skipped_reason"] == "manual_round"
    assert result["created_task_ids"] == []
    assert result["existing_task_count"] == 1

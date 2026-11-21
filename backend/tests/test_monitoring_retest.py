"""固定周期复测：到期建轮、API 派发、应用内待手测、跳过未结束轮次。"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringRetestPlan,
    MonitoringRound,
    MonitoringTask,
    OutboxEvent,
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
from app.services.monitoring_retest import (
    _select_api_entries,
    _select_app_search_entries,
    create_plan,
    run_due_retest_plans,
)


def _seed_engine_entry(
    db,
    suffix: str,
    code: str,
    entry_type: EngineEntryType,
    *,
    entry_active: bool = True,
) -> tuple[AiEngine, AiEngineEntry]:
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
        entry_type=entry_type,
        name=f"入口-{code}",
        supports_search=True,
        is_active=entry_active,
    )
    db.add(entry)
    db.flush()
    return engine, entry


def _seed_question(db, project, code: str, question_type: QuestionType) -> QuestionVersion:
    question = Question(
        project_id=project.id,
        code=code,
        title=f"问题 {code}",
        question_type=question_type,
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
        text=f"正文 {code}",
    )
    db.add(version)
    db.flush()
    return version


def _seed_plan(db, project, editor, scope=None):
    _, api_entry = _seed_engine_entry(
        db, uuid.uuid4().hex[:6], "api", EngineEntryType.API
    )
    _, app_entry = _seed_engine_entry(
        db, uuid.uuid4().hex[:6], "app", EngineEntryType.APP_SEARCH, entry_active=False
    )
    _seed_question(db, project, "Q01", QuestionType.BRAND)
    _seed_question(db, project, "Q02", QuestionType.GENERAL)
    plan = create_plan(
        db,
        project_id=project.id,
        actor_id=editor.id,
        name=f"每周复测-{uuid.uuid4().hex[:6]}",
        interval_days=7,
        first_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        entry_scope=scope or ["api", "app_search"],
        samples_per_cell=1,
    )
    db.flush()
    # 测试库可能与开发库共用；临时停用其他已落库计划，避免它们按模拟时间到期后
    # 混入 created/skipped 计数。测试事务回滚后恢复原状态。
    for other in db.scalars(
        select(MonitoringRetestPlan).where(MonitoringRetestPlan.id != plan.id)
    ).all():
        other.enabled = False
    db.flush()
    return plan, api_entry, app_entry


def test_due_plan_creates_one_round_and_dispatches_only_api(
    db, project_factory, user_factory, member_factory
):
    project = project_factory(f"retest-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"retest-ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    plan, api_entry, app_entry = _seed_plan(db, project, editor)
    now = plan.next_run_at + timedelta(seconds=1)

    result = run_due_retest_plans(db, now=now)

    assert result["created_count"] == 1, result
    assert result["skipped_count"] == 0
    round_row = db.scalar(
        select(MonitoringRound).where(
            MonitoringRound.project_id == project.id,
            MonitoringRound.retest_plan_id == plan.id,
        )
    )
    assert round_row is not None
    assert round_row.status == RoundStatus.RUNNING
    assert round_row.scheduled_for is not None

    tasks = db.scalars(
        select(MonitoringTask).where(MonitoringTask.round_id == round_row.id)
    ).all()
    api_entries = _select_api_entries(db)
    app_entries = _select_app_search_entries(db)
    assert len(tasks) == 2 * (len(api_entries) + len(app_entries))
    assert any(task.engine_entry_id == api_entry.id for task in tasks)
    assert any(task.engine_entry_id == app_entry.id for task in tasks)
    assert all(task.status == TaskStatus.PENDING for task in tasks)

    outbox = db.scalars(
        select(OutboxEvent).where(
            OutboxEvent.project_id == project.id,
            OutboxEvent.topic == "monitoring.task.execute",
        )
    ).all()
    api_task_ids = {
        str(task.id)
        for task in tasks
        if {
            entry.id: entry.entry_type
            for entry in api_entries
        }.get(task.engine_entry_id) == EngineEntryType.API
    }
    dispatched_task_ids = {
        str(event.payload.get("task_id")) for event in outbox
    }
    assert dispatched_task_ids == api_task_ids
    assert plan.next_run_at > now

    again = run_due_retest_plans(db, now=now)
    assert again["due_plan_count"] == 0
    assert again["created_count"] == 0


def test_open_round_is_skipped_and_next_run_advances(
    db, project_factory, user_factory, member_factory
):
    project = project_factory(f"retest-skip-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"retest-skip-ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    plan, _api_entry, _app_entry = _seed_plan(db, project, editor)
    first_now = plan.next_run_at + timedelta(seconds=1)

    first = run_due_retest_plans(db, now=first_now)
    assert first["created_count"] == 1
    first_round = db.scalar(
        select(MonitoringRound).where(
            MonitoringRound.project_id == project.id,
            MonitoringRound.retest_plan_id == plan.id,
        )
    )
    assert first_round is not None

    # 手工把计划推到下一次槽位；上一轮仍 running，应该跳过而不是建第二轮。
    plan.next_run_at = first_now + timedelta(days=7)
    db.flush()
    second = run_due_retest_plans(db, now=first_now + timedelta(days=7, seconds=1))

    assert second["skipped_count"] == 1
    assert second["skipped"][0]["reason"] == "previous_round_open"
    rounds = db.scalars(
        select(MonitoringRound).where(
            MonitoringRound.project_id == project.id,
            MonitoringRound.retest_plan_id == plan.id,
        )
    ).all()
    assert len(rounds) == 1


def test_api_create_list_update_and_run_now(
    client, db, project_factory, user_factory, member_factory
):
    from app.core.security import create_access_token

    project = project_factory(f"retest-api-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"retest-api-ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _seed_engine_entry(db, uuid.uuid4().hex[:6], "api", EngineEntryType.API)
    _seed_engine_entry(
        db, uuid.uuid4().hex[:6], "app", EngineEntryType.APP_SEARCH, entry_active=False
    )
    _seed_question(db, project, "Q01", QuestionType.GENERAL)
    headers = {
        "Authorization": f"Bearer {create_access_token(editor.id, token_version=editor.token_version)}"
    }
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    created = client.post(
        f"/api/v1/projects/{project.id}/monitoring/retest-plans",
        json={
            "name": "API 复测",
            "interval_days": 7,
            "first_run_at": future,
            "entry_scope": ["api", "app_search"],
            "samples_per_cell": 1,
            "enabled": True,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["data"]["id"]

    listed = client.get(
        f"/api/v1/projects/{project.id}/monitoring/retest-plans", headers=headers
    )
    assert listed.status_code == 200
    assert listed.json()["data"][0]["name"] == "API 复测"

    updated = client.patch(
        f"/api/v1/projects/{project.id}/monitoring/retest-plans/{plan_id}",
        json={"enabled": False},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["enabled"] is False

    run = client.post(
        f"/api/v1/projects/{project.id}/monitoring/retest-plans/{plan_id}/run",
        headers=headers,
    )
    assert run.status_code == 200, run.text
    assert run.json()["data"]["created_task_count"] > 0
    assert run.json()["data"]["api_task_count"] > 0
    assert run.json()["data"]["manual_task_count"] > 0

"""异常预警：五类默认规则、提及率下降触发、24 小时去重、确认留痕。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    AlertEvent,
    AlertRule,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    AlertEventStatus,
    AnswerKind,
    EngineEntryType,
    QuestionStatus,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _setup(db, project):
    question = Question(
        project_id=project.id,
        code=f"Q-{uuid.uuid4().hex[:6]}",
        title="广州AI培训哪家好",
        question_type=QuestionType.BRAND,
        audience="广州",
        intent="选机构",
        priority=100,
        status=QuestionStatus.ACTIVE,
        current_version_no=1,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="广州AI培训哪家好")
    engine = AiEngine(
        code=f"eng-{uuid.uuid4().hex[:6]}", name="预警测试引擎", vendor="测试",
        supports_search=True, supports_citation=True, is_active=True,
    )
    db.add_all([version, engine])
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.API, name="入口", supports_search=True, is_active=True)
    round_row = MonitoringRound(project_id=project.id, seq=1, name="预警轮", is_baseline=False, status=RoundStatus.RUNNING)
    db.add_all([entry, round_row])
    db.flush()
    task = MonitoringTask(
        project_id=project.id, round_id=round_row.id, question_version_id=version.id,
        engine_entry_id=entry.id, sampling_no=1, sampling_mode=SamplingMode.SEARCH_ON, status=TaskStatus.DONE,
    )
    db.add(task)
    db.flush()
    now = datetime.now(timezone.utc)
    for index in range(5):
        db.add(MonitoringSample(
            project_id=project.id, task_id=task.id, attempt_no=index + 1,
            status=SampleStatus.HIT, sampling_mode=SamplingMode.SEARCH_ON, answer_kind=AnswerKind.ANSWER,
            brand_mentioned=True, brand_list_rank=1, brand_recommendation=True,
            sampled_at=now - timedelta(days=10),
        ))
    for index in range(5):
        db.add(MonitoringSample(
            project_id=project.id, task_id=task.id, attempt_no=index + 6,
            status=SampleStatus.HIT, sampling_mode=SamplingMode.SEARCH_ON, answer_kind=AnswerKind.ANSWER,
            brand_mentioned=False, brand_list_rank=None,
            sampled_at=now - timedelta(days=1),
        ))
    db.flush()


def test_alert_rules_and_mention_drop_deduped(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"alert-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"alert-editor-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _setup(db, project)

    rules = client.get(f"/api/v1/projects/{project.id}/alerts/rules", headers=_auth(editor))
    assert rules.status_code == 200, rules.text
    assert {item["code"] for item in rules.json()["data"]} == {
        "mention_rate_drop", "recommendation_rate_drop", "competitor_outrank",
        "negative_share_rise", "collection_failure_rate",
    }

    first = client.post(f"/api/v1/projects/{project.id}/alerts/evaluate", json={}, headers=_auth(editor))
    assert first.status_code == 200, first.text
    codes = {event["code"] for event in first.json()["data"]["events"]}
    assert "mention_rate_drop" in codes

    event = db.scalar(select(AlertEvent).where(
        AlertEvent.project_id == project.id,
        AlertEvent.code == "mention_rate_drop",
    ))
    assert event is not None
    assert event.status.value == "open"
    assert event.metric_value is not None and float(event.metric_value) == 0.0
    assert event.baseline_value is not None and float(event.baseline_value) == 1.0

    second = client.post(f"/api/v1/projects/{project.id}/alerts/evaluate", json={}, headers=_auth(editor))
    assert second.status_code == 200, second.text
    db.refresh(event)
    assert event.trigger_count == 2
    rows = db.scalars(select(AlertEvent).where(
        AlertEvent.project_id == project.id, AlertEvent.code == "mention_rate_drop"
    )).all()
    assert len(rows) == 1

    ack = client.post(
        f"/api/v1/projects/{project.id}/alerts/events/{event.id}/ack",
        json={"note": "已核实，本周补内容"},
        headers=_auth(editor),
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["data"]["status"] == AlertEventStatus.ACKNOWLEDGED.value
    assert ack.json()["data"]["note"] == "已核实，本周补内容"

    rule = db.scalar(select(AlertRule).where(
        AlertRule.project_id == project.id, AlertRule.code == "mention_rate_drop"
    ))
    assert rule is not None
    updated = client.patch(
        f"/api/v1/projects/{project.id}/alerts/rules/{rule.id}",
        json={"thresholds": {"drop_abs": 0.2}, "is_enabled": False},
        headers=_auth(editor),
    )
    assert updated.status_code == 200, updated.text
    assert float(updated.json()["data"]["thresholds"]["drop_abs"]) == 0.2
    assert updated.json()["data"]["is_enabled"] is False

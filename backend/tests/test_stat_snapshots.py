"""每轮统计快照冻结接口回归。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
    StatSnapshot,
)
from app.models.enums import (
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


def _seed(db, project: Project) -> MonitoringRound:
    suffix = uuid.uuid4().hex[:6]
    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="快照题目",
        question_type=QuestionType.GENERAL,
        status=QuestionStatus.ACTIVE,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text="快照题目",
        question_type=QuestionType.GENERAL,
    )
    engine = AiEngine(code=f"e-{suffix}", name="引擎", vendor="测试", supports_search=True)
    db.add_all([version, engine])
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        name="网页端",
        entry_type=EngineEntryType.WEB_USER,
        is_active=True,
    )
    db.add(entry)
    db.flush()
    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="快照轮次",
        status=RoundStatus.RUNNING,
        analysis_config_snapshot={"rules": {"mention_matcher": "substring-regex-v1"}},
        analysis_config_hash="a" * 64,
        analysis_config_version="substring-regex-v1",
        analysis_config_captured_at=datetime.now(timezone.utc),
    )
    db.add(round_row)
    db.flush()
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.DONE,
    )
    db.add(task)
    db.flush()
    db.add(
        MonitoringSample(
            project_id=project.id,
            task_id=task.id,
            attempt_no=1,
            status=SampleStatus.HIT,
            sampling_mode=SamplingMode.SEARCH_ON,
            sampled_at=datetime.now(timezone.utc),
            answer_kind=AnswerKind.ANSWER,
            brand_mentioned=True,
        )
    )
    db.flush()
    return round_row


def test_freeze_round_snapshot_is_immutable_and_contains_scope_and_metrics(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"snap-{suffix}")
    operator = user_factory(f"snap-operator-{suffix}")
    member_factory(project, operator, RoleCode.EDITOR)
    round_row = _seed(db, project)

    response = client.post(
        f"/api/v1/projects/{project.id}/stats/snapshots",
        params={"round_id": str(round_row.id)},
        headers=_auth(operator),
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["round_id"] == str(round_row.id)
    assert len(data["snapshot_hash"]) == 64
    assert data["rule_version"] == "stat-snapshot-v2"
    assert data["scope"]["round"]["seq"] == 1
    assert data["scope"]["question_versions"][0]["question_type"] == "general"
    assert data["metrics"]["denominators"]["valid_answers"] == 1
    assert data["metrics"]["overview"]["brand_mentioned_answers"] == 1

    # 同一轮再次冻结必须冲突，不能覆盖第一份
    again = client.post(
        f"/api/v1/projects/{project.id}/stats/snapshots",
        params={"round_id": str(round_row.id)},
        headers=_auth(operator),
    )
    assert again.status_code == 409, again.text
    assert again.json()["error"]["code"] == "snapshot_exists"

    listed = client.get(
        f"/api/v1/projects/{project.id}/stats/snapshots",
        headers=_auth(operator),
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["data"]) == 1
    assert db.scalar(select(StatSnapshot).where(StatSnapshot.project_id == project.id)) is not None


def test_snapshot_list_and_detail_are_project_scoped(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"snap-scope-{suffix}")
    other = project_factory(f"snap-other-{suffix}")
    viewer = user_factory(f"snap-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.EDITOR)
    round_row = _seed(db, project)
    created = client.post(
        f"/api/v1/projects/{project.id}/stats/snapshots",
        params={"round_id": str(round_row.id)},
        headers=_auth(viewer),
    )
    assert created.status_code == 201, created.text
    snapshot_id = created.json()["data"]["snapshot_id"]

    detail = client.get(
        f"/api/v1/projects/{other.id}/stats/snapshots/{snapshot_id}",
        headers=_auth(viewer),
    )
    assert detail.status_code in (403, 404)

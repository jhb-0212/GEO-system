"""权威事实库、审批流与回答事实核验回归。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    AnswerFactClaim,
    CorrectionTask,
    Fact,
    FactVersion,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import (
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


def _make_sample(db, project: Project) -> MonitoringSample:
    suffix = uuid.uuid4().hex[:6]
    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="事实核验测试题",
        question_type=QuestionType.GENERAL,
        status=QuestionStatus.ACTIVE,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text=question.title,
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
        name="事实核验轮次",
        status=RoundStatus.RUNNING,
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
    sample = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        status=SampleStatus.HIT,
        sampling_mode=SamplingMode.SEARCH_ON,
        sampled_at=datetime.now(timezone.utc),
        raw_answer="广州基地课程周期为 6 个月。",
    )
    db.add(sample)
    db.flush()
    return sample


def _create_approved_fact(
    client, db, project, editor, reviewer, *, key="课程周期", value="6 个月"
) -> dict:
    created = client.post(
        f"/api/v1/projects/{project.id}/facts",
        json={
            "fact_type": "course_duration",
            "fact_key": key,
            "fact_value": value,
            "source_document": "2026 招生简章.pdf",
            "source_url": "https://www.gdccai.com/course",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    fact_id = created.json()["data"]["id"]
    submitted = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/submit",
        headers=_auth(editor),
    )
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/review",
        json={"decision": "approved", "business_confirmed": False},
        headers=_auth(reviewer),
    )
    assert approved.status_code == 200, approved.text
    return approved.json()["data"]


def test_fact_approval_writes_full_version_history(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"fact-{suffix}")
    editor = user_factory(f"fact-editor-{suffix}")
    reviewer = user_factory(f"fact-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)

    fact = _create_approved_fact(client, db, project, editor, reviewer)
    assert fact["approval_status"] == "approved"
    assert fact["approved_by"] is not None

    versions = client.get(
        f"/api/v1/projects/{project.id}/facts/{fact['id']}/versions",
        headers=_auth(editor),
    )
    assert versions.status_code == 200, versions.text
    rows = versions.json()["data"]
    assert [row["action"] for row in rows] == ["approved", "submitted", "created"]
    approved_snapshot = rows[0]["snapshot"]
    assert approved_snapshot["approval_status"] == "approved"
    assert approved_snapshot["source_document"] == "2026 招生简章.pdf"
    assert approved_snapshot["version_no"] == 1
    assert rows[1]["previous_snapshot"]["approval_status"] == "draft"


def test_employment_guarantee_requires_business_confirmation(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"fact-guard-{suffix}")
    editor = user_factory(f"fact-guard-editor-{suffix}")
    reviewer = user_factory(f"fact-guard-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    created = client.post(
        f"/api/v1/projects/{project.id}/facts",
        json={
            "fact_type": "employment_service",
            "fact_key": "就业承诺",
            "fact_value": "入学即签订就业协议，保证就业。",
            "source_document": "就业服务说明.pdf",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    fact_id = created.json()["data"]["id"]
    assert client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/submit",
        headers=_auth(editor),
    ).status_code == 200

    blocked = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/review",
        json={"decision": "approved"},
        headers=_auth(reviewer),
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "employment_guarantee_unconfirmed"

    approved = client.post(
        f"/api/v1/projects/{project.id}/facts/{fact_id}/review",
        json={
            "decision": "approved",
            "business_confirmed": True,
            "business_confirmed_note": "业务负责人 2026-11-18 书面确认（邮件编号 A-102）",
        },
        headers=_auth(reviewer),
    )
    assert approved.status_code == 200, approved.text
    data = approved.json()["data"]
    assert data["approval_status"] == "approved"
    assert data["business_confirmed"] is True


def test_revision_of_approved_fact_returns_to_draft_with_snapshot(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"fact-rev-{suffix}")
    editor = user_factory(f"fact-rev-editor-{suffix}")
    reviewer = user_factory(f"fact-rev-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    fact = _create_approved_fact(client, db, project, editor, reviewer)

    updated = client.patch(
        f"/api/v1/projects/{project.id}/facts/{fact['id']}",
        json={"fact_value": "8 个月", "change_note": "招生简章更新"},
        headers=_auth(editor),
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["approval_status"] == "draft"
    assert data["version_no"] == 2
    assert data["approved_by"] is None

    versions = client.get(
        f"/api/v1/projects/{project.id}/facts/{fact['id']}/versions",
        headers=_auth(editor),
    )
    rev = versions.json()["data"][0]
    assert rev["action"] == "revised"
    assert rev["snapshot"]["fact_value"] == "8 个月"
    assert rev["previous_snapshot"]["fact_value"] == "6 个月"


def test_wrong_claim_creates_correction_task(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"claim-{suffix}")
    editor = user_factory(f"claim-editor-{suffix}")
    reviewer = user_factory(f"claim-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    fact = _create_approved_fact(client, db, project, editor, reviewer)
    sample = _make_sample(db, project)

    created = client.post(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}/fact-claims",
        json={
            "claim_text": "课程周期只有 3 个月",
            "fact_id": fact["id"],
            "source_url": "https://www.gdccai.com/faq",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    claim_id = created.json()["data"]["id"]

    reviewed = client.patch(
        f"/api/v1/projects/{project.id}/fact-claims/{claim_id}",
        json={"verdict": "wrong", "review_note": "与已批准简章不一致"},
        headers=_auth(reviewer),
    )
    assert reviewed.status_code == 200, reviewed.text
    claim = reviewed.json()["data"]
    assert claim["verdict"] == "wrong"
    assert claim["correction_task_id"] is not None
    assert claim["source_url"] == "https://www.gdccai.com/faq"

    tasks = client.get(
        f"/api/v1/projects/{project.id}/correction-tasks",
        headers=_auth(editor),
    )
    assert tasks.status_code == 200, tasks.text
    assert len(tasks.json()["data"]) == 1
    assert tasks.json()["data"][0]["status"] == "open"
    assert tasks.json()["data"][0]["source_url"] == "https://www.gdccai.com/faq"

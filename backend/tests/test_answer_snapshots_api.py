"""原始回答快照：追加即冻结、重复存档不覆盖、漂移只比对回答文本。

钉住四条：
1. 存档成功返回内容哈希与回答哈希，引用清单进 payload；
2. 同一采样再次存档返回既有记录（created=False），哈希不变；
3. 样本 raw_answer 被改写后，既有快照不变，只在列表上标 answer_drift；
4. 没有回答内容的样本不落空快照，批量补档只计数。
"""

import uuid
from datetime import UTC, datetime

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    CitationPageType,
    CitationReviewStatus,
    EngineEntryType,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    SourceCategory,
    TaskStatus,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _task(db, project) -> MonitoringTask:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"sn-{suffix}", name="快照引擎", vendor="测试", supports_search=True,
                      supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    db.add(entry)
    question = Question(project_id=project.id, code=f"SN-{suffix}", title="快照题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="快照题正文")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="快照轮次", status=RoundStatus.RUNNING)
    db.add_all([version, round_row])
    db.flush()
    task = MonitoringTask(project_id=project.id, round_id=round_row.id, question_version_id=version.id,
                          engine_entry_id=entry.id, sampling_no=1, sampling_mode=SamplingMode.SEARCH_ON,
                          status=TaskStatus.DONE)
    db.add(task)
    db.flush()
    return task


def _sample(db, project, task, *, attempt: int, answer: str | None) -> MonitoringSample:
    sample = MonitoringSample(project_id=project.id, task_id=task.id, attempt_no=attempt,
                             status=SampleStatus.HIT, sampled_at=datetime.now(UTC),
                             raw_answer=answer, brand_mentioned=True)
    db.add(sample)
    db.flush()
    return sample


def test_snapshot_is_immutable_and_flags_answer_drift(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sn-{suffix}")
    editor = user_factory(f"sn-e-{suffix}")
    viewer = user_factory(f"sn-v-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, viewer, RoleCode.VIEWER)
    task = _task(db, project)
    sample = _sample(db, project, task, attempt=1, answer="原始回答：广州基地开设 AI 实训课程。")
    db.add(MonitoringCitation(
        project_id=project.id, sample_id=sample.id,
        raw_url="https://zhihu.com/p/1", normalized_url="zhihu.com/p/1", domain="zhihu.com",
        is_brand_related=True, page_type=CitationPageType.ARTICLE,
        source_category=SourceCategory.SOCIAL_COMMUNITY, review_status=CitationReviewStatus.MANUAL_CONFIRMED,
    ))
    db.flush()

    created = client.post(f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}/snapshot", headers=_auth(editor))
    assert created.status_code == 200, created.text
    first = created.json()["data"]
    assert first["created"] is True
    assert len(first["content_hash"]) == 64 and len(first["answer_hash"]) == 64
    assert first["citation_count"] == 1
    assert first["question_code"].startswith("SN-")
    assert first["answer_drift"] is False

    again = client.post(f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}/snapshot", headers=_auth(editor))
    second = again.json()["data"]
    assert second["created"] is False
    assert second["id"] == first["id"]
    assert second["content_hash"] == first["content_hash"]

    # 改写样本原文后，快照内容不动，列表上出现漂移标记
    sample.raw_answer = "原始回答：已被人改写过。"
    db.flush()
    listed = client.get(f"/api/v1/projects/{project.id}/monitoring/snapshots?page=1&page_size=20", headers=_auth(viewer))
    assert listed.status_code == 200
    rows = listed.json()["data"]
    assert len(rows) == 1
    assert rows[0]["answer_drift"] is True
    assert rows[0]["answer_hash"] == first["answer_hash"]

    detail = client.get(f"/api/v1/projects/{project.id}/monitoring/snapshots/{first['id']}", headers=_auth(viewer)).json()["data"]
    assert detail["payload"]["answer"]["raw_answer"] == "原始回答：广州基地开设 AI 实训课程。"
    assert detail["payload"]["citations"][0]["domain"] == "zhihu.com"
    assert detail["answer_drift"] is True


def test_snapshot_rejects_samples_without_answer(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sn-empty-{suffix}")
    editor = user_factory(f"sn-empty-e-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    task = _task(db, project)
    empty = _sample(db, project, task, attempt=1, answer=None)
    filled = _sample(db, project, task, attempt=2, answer="有回答")

    response = client.post(f"/api/v1/projects/{project.id}/monitoring/samples/{empty.id}/snapshot", headers=_auth(editor))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "sample_no_answer"

    batch = client.post(f"/api/v1/projects/{project.id}/monitoring/snapshots/capture-batch?limit=50", headers=_auth(editor))
    assert batch.status_code == 200, batch.text
    result = batch.json()["data"]
    assert result["captured"] == 1
    assert result["missing_answer"] == 1
    assert result["candidates"] == 2

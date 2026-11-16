"""B5 样本回看与人工复核骨架测试。

覆盖：reviewer 复核归入 hit/miss、editor 越权 403、跨项目 403、终态样本 409、
详情回看内联引用与证据文件、无 token 401。

说明：成功采集路径依赖真实适配器，样本夹具直接以 ORM 落库 RUNNING 状态；
权限码（evidence.review 复用 vs 新增 sample.review）待 C 复核后调整。
"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    AuditLog,
    Channel,
    EvidenceFile,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    ChannelCategory,
    ChannelStatus,
    CitationUsage,
    EngineEntryType,
    EvidenceFileType,
    QuestionStatus,
    QuestionType,
    ReviewResult,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services import monitoring_collection
from app.services.monitoring_extraction import AnswerPayload


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _seed_sample_chain(db, project, *, sample_status=SampleStatus.RUNNING):
    """落库 轮次 → 任务 → 样本 → 引用 → 证据文件，返回样本及关联记录。"""
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(
        code=f"eng-{suffix}",
        name="引擎",
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
        name="网页端",
        supports_search=True,
        is_active=True,
    )
    db.add(entry)
    db.flush()

    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="测试问题",
        question_type=QuestionType.GENERAL,
        audience="测试人群",
        intent="测试意图",
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
        text="测试正文",
    )
    db.add(version)
    db.flush()

    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="轮次-1",
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
        status=sample_status,
        sampling_mode=SamplingMode.SEARCH_ON,
        raw_answer="原始回答文本",
        brand_mentioned=True,
    )
    db.add(sample)
    db.flush()
    citation = MonitoringCitation(
        project_id=project.id,
        sample_id=sample.id,
        raw_url="https://example.com/a",
        normalized_url="https://example.com/a",
        domain="example.com",
        citation_usage=CitationUsage.CITED,
        is_brand_related=True,
    )
    db.add(citation)
    db.flush()
    evidence = EvidenceFile(
        project_id=project.id,
        sample_id=sample.id,
        storage_key=f"samples/{sample.id}/shot.png",
        file_type=EvidenceFileType.SCREENSHOT,
        content_type="image/png",
        byte_size=1024,
    )
    db.add(evidence)
    db.flush()
    return sample, citation, evidence


def test_reviewer_can_review_manual_review_sample(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"b5-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample, _, _ = _seed_sample_chain(db, project, sample_status=SampleStatus.MANUAL_REVIEW)

    resp = client.post(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}/manual-review",
        json={"review_result": ReviewResult.HIT.value, "review_note": "人工确认命中"},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == SampleStatus.HIT.value
    assert data["review_result"] == ReviewResult.HIT.value

    db.refresh(sample)
    assert sample.status == SampleStatus.HIT
    assert sample.review_result == ReviewResult.HIT
    assert sample.reviewed_by == reviewer.id
    assert sample.reviewed_at is not None

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "monitoring.sample_review",
            AuditLog.target_id == sample.id,
        )
    )
    assert audit is not None


def test_sample_without_raw_answer_cannot_be_reviewed(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"b5-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample, _, _ = _seed_sample_chain(db, project, sample_status=SampleStatus.MANUAL_REVIEW)
    sample.raw_answer = None
    db.flush()
    resp = client.post(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}/manual-review",
        json={"review_result": ReviewResult.HIT.value}, headers=_auth(reviewer),
    )
    assert resp.status_code == 409


def test_editor_cannot_review_sample(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b5-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    sample, _, _ = _seed_sample_chain(db, project)

    resp = client.post(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}/manual-review",
        json={"review_result": ReviewResult.MISS.value},
        headers=_auth(editor),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "insufficient_permission"


def test_cross_project_sample_forbidden(
    client, db, project_factory, user_factory, member_factory
):
    p1 = project_factory(f"b5a-{uuid.uuid4().hex[:6]}")
    p2 = project_factory(f"b5b-{uuid.uuid4().hex[:6]}")
    outsider = user_factory(f"out-{uuid.uuid4().hex[:6]}")
    member_factory(p2, outsider, RoleCode.REVIEWER)
    sample, _, _ = _seed_sample_chain(db, p1)

    resp = client.post(
        f"/api/v1/projects/{p2.id}/monitoring/samples/{sample.id}/manual-review",
        json={"review_result": ReviewResult.HIT.value},
        headers=_auth(outsider),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "project_forbidden"


def test_review_terminal_sample_rejected(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"b5-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample, _, _ = _seed_sample_chain(db, project, sample_status=SampleStatus.HIT)

    resp = client.post(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}/manual-review",
        json={"review_result": ReviewResult.MISS.value},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "task_rejected"


def test_get_sample_detail_includes_citations_and_evidence(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"b5-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"vw-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    sample, citation, evidence = _seed_sample_chain(db, project)

    resp = client.get(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}",
        headers=_auth(viewer),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["id"] == str(sample.id)
    assert data["raw_answer"] == "原始回答文本"
    assert len(data["citations"]) == 1
    assert data["citations"][0]["citation_id"] == str(citation.id)
    assert data["citations"][0]["channel_id"] is None
    assert data["citations"][0]["channel_name"] is None
    assert data["citations"][0]["channel_category"] is None
    assert len(data["evidence_files"]) == 1
    assert data["evidence_files"][0]["evidence_id"] == str(evidence.id)


def test_get_sample_detail_includes_citation_channel_identity(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"b5-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"vw-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    sample, citation, _ = _seed_sample_chain(db, project)
    channel = Channel(
        project_id=project.id,
        code=f"src-{uuid.uuid4().hex[:6]}",
        name="知乎",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.OBSERVED,
        primary_domain="zhihu.com",
    )
    db.add(channel)
    db.flush()
    citation.channel_id = channel.id
    db.commit()

    resp = client.get(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}",
        headers=_auth(viewer),
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["data"]["citations"][0]
    assert item["channel_id"] == str(channel.id)
    assert item["channel_name"] == "知乎"
    assert item["channel_category"] == "content_platform"


def test_get_sample_without_token_unauthorized(client, db, project_factory):
    project = project_factory(f"b5-{uuid.uuid4().hex[:6]}")
    sample, _, _ = _seed_sample_chain(db, project)

    resp = client.get(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}"
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_replay_sample_uses_stored_request(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project = project_factory(f"b5-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    sample, _, _ = _seed_sample_chain(db, project)
    task = db.get(MonitoringTask, sample.task_id)

    trace_id = "trace-replay-test"
    task.trace_id = trace_id
    sample.trace_id = trace_id
    sample.request_payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "留存的原始问题"}],
    }
    db.flush()

    class ReplayAdapter:
        def __init__(self):
            self.last_request_payload = None
            self.seen = None

        def collect_with_request(self, _task, request_payload):
            self.seen = request_payload
            self.last_request_payload = request_payload
            return AnswerPayload(
                text="回放回答",
                raw_response={"usage": {"prompt_tokens": 11, "completion_tokens": 7}},
            )

    adapter = ReplayAdapter()
    monkeypatch.setattr(
        monitoring_collection,
        "build_entry_adapter",
        lambda db, entry: adapter,
    )

    resp = client.post(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}/replay",
        headers=_auth(editor),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["used_stored_request"] is True
    assert data["trace_id"] == trace_id
    assert data["total_tokens"] == 18
    assert adapter.seen == sample.request_payload

    replay_sample = db.get(MonitoringSample, uuid.UUID(data["sample_id"]))
    assert replay_sample.attempt_no == 2
    assert replay_sample.trace_id == trace_id
    assert replay_sample.total_tokens == 18

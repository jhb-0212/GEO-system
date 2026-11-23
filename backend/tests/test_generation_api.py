"""G1/G2 生成批次：只从缺口出题、只出模板草稿、必须人工审。

钉住六条：
1. 没有候选时明确报错，不建空批次；
2. 机会来源的批次项带 `opportunity_id` 与简报（可回溯证据），状态是 queued；
3. 跑批后草稿落库，正文写明「模板合成」，计数与状态一致；
4. 传 `engine_code` 直接报 `model_generation_disabled`（不偷跑付费模型）；
5. 审稿标记可改，且不会自动发布（没有产生发布任务）；
6. 导出带审计、CSV 可解析。
"""

import csv
import io
import uuid
from datetime import UTC, datetime

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    Faq,
    GenerationBatch,
    GenerationItem,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Opportunity,
    PublishTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    EngineEntryType,
    FaqStatus,
    OpportunityGapType,
    OpportunityStatus,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _setup(project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"gen-{suffix}")
    user = user_factory(f"gen-u-{suffix}")
    member_factory(project, user, RoleCode.EDITOR)
    return project, user


def _opportunity(db, project, title="竞品被引用而本品牌缺席"):
    row = Opportunity(
        project_id=project.id,
        title=title,
        gap_type=OpportunityGapType.MEDIA_REPORT,
        evidence_refs=[{"sample_id": "x", "citation_id": "y"}],
        score_factors={"citation_gap": 1},
        score_weights={"citation_gap": 1},
        priority_score=0.8,
        status=OpportunityStatus.OPEN,
    )
    db.add(row)
    db.commit()
    return row


def _create(client, project, user, **body):
    return client.post(
        f"/api/v1/projects/{project.id}/generation-batches", json=body, headers=_auth(user)
    )


def test_no_candidates_is_rejected(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    resp = _create(client, project, user, name="空批次", source="opportunity", limit=5)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "no_generation_candidates"
    assert db.query(GenerationBatch).filter(GenerationBatch.project_id == project.id).count() == 0


def test_opportunity_batch_carries_evidence(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    opp = _opportunity(db, project)
    resp = _create(client, project, user, name="缺口批次", source="opportunity", limit=5)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "queued"
    assert data["totals"]["total"] == 1
    item = data["items"][0]
    assert item["opportunity_id"] == str(opp.id)
    assert item["status"] == "pending"
    assert item["brief"]["gap_type"] == "media_report"
    assert item["brief"]["evidence_refs"]
    assert item["brief"]["guidance"]


def test_run_drafts_with_template_only(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    _opportunity(db, project)
    db.add(
        Faq(
            project_id=project.id,
            question="实训多久？",
            answer="三个月项目制。",
            status=FaqStatus.PUBLISHED,
        )
    )
    db.commit()
    batch_id = _create(client, project, user, name="跑批", source="opportunity").json()["data"]["batch_id"]

    resp = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch_id}/run", headers=_auth(user)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "completed"
    assert data["totals"]["drafted"] == 1
    item = data["items"][0]
    assert item["status"] == "drafted"
    assert item["generation_mode"] == "template"
    assert "模板合成（未调用模型）" in item["draft_body"]
    assert "三个月项目制" in item["draft_body"]


def test_model_generation_is_off_by_default(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    _opportunity(db, project)
    resp = _create(
        client, project, user, name="模型批次", source="opportunity", engine_code="deepseek"
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "model_generation_disabled"


def test_review_flag_does_not_publish(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    _opportunity(db, project)
    batch = _create(client, project, user, name="审稿", source="opportunity").json()["data"]
    batch_id = batch["batch_id"]
    item_id = batch["items"][0]["item_id"]
    client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch_id}/run", headers=_auth(user)
    )

    resp = client.patch(
        f"/api/v1/projects/{project.id}/generation-batches/{batch_id}/items/{item_id}",
        json={"reviewed": True},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["reviewed"] is True
    # 审稿只改标记：不产生发布任务
    assert db.query(PublishTask).filter(PublishTask.project_id == project.id).count() == 0
    stored = db.query(GenerationItem).filter(GenerationItem.id == uuid.UUID(item_id)).one()
    assert stored.reviewed is True


def test_export_csv_and_question_source(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    # 问题来源：造一条「测过但从没提及」的完整监测链路（问题→版本→任务→样本）
    question = Question(
        project_id=project.id, code="Q1", title="广州 AI 实训哪家好", question_type=QuestionType.BRAND
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(
        project_id=project.id, question_id=question.id, version_no=1, text="广州 AI 实训哪家好"
    )
    db.add(version)
    db.flush()
    engine = AiEngine(
        code=f"gen-eng-{uuid.uuid4().hex[:6]}",
        name="生成测试引擎",
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
        name="生成测试入口",
        supports_search=True,
        is_active=True,
    )
    db.add(entry)
    db.flush()
    round_row = MonitoringRound(
        project_id=project.id, seq=1, name="生成测试轮次", is_baseline=True, status=RoundStatus.RUNNING
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

    # 没有样本时不该出现在候选里（只认「测过」）
    assert _create(client, project, user, name="无样本", source="question").status_code == 400

    db.add(
        MonitoringSample(
            project_id=project.id,
            task_id=task.id,
            attempt_no=1,
            brand_mentioned=False,
            status=SampleStatus.MISS,
            sampling_mode=SamplingMode.SEARCH_ON,
            sampled_at=datetime.now(UTC),
        )
    )
    db.commit()

    resp = _create(client, project, user, name="问题批次", source="question")
    assert resp.status_code == 200, resp.text
    batch_id = resp.json()["data"]["batch_id"]
    client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch_id}/run", headers=_auth(user)
    )

    export = client.get(
        f"/api/v1/projects/{project.id}/generation-batches/{batch_id}/export", headers=_auth(user)
    )
    assert export.status_code == 200, export.text
    rows = list(csv.DictReader(io.StringIO(export.text)))
    assert len(rows) == 1
    assert rows[0]["标题"] == "广州 AI 实训哪家好"
    assert rows[0]["来源"] == "question"

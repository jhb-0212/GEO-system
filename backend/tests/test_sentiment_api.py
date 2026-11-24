"""情绪原文统计：三档计数、可信度排序与人工标注边界。"""

import uuid

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
    QuestionStatus,
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


def _seed_sample(db, project) -> MonitoringSample:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"eng-{suffix}", name="引擎", vendor="测试", supports_search=True, supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", supports_search=True, is_active=True)
    db.add(entry)
    db.flush()
    question = Question(
        project_id=project.id, code=f"Q-{suffix}", title="测试问题", question_type=QuestionType.GENERAL,
        audience="人群", intent="意图", priority=100, status=QuestionStatus.ACTIVE, current_version_no=1,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="测试正文")
    db.add(version)
    db.flush()
    round_row = MonitoringRound(project_id=project.id, seq=1, name="轮次-1", status=RoundStatus.RUNNING)
    db.add(round_row)
    db.flush()
    task = MonitoringTask(
        project_id=project.id, round_id=round_row.id, question_version_id=version.id,
        engine_entry_id=entry.id, sampling_no=1, sampling_mode=SamplingMode.SEARCH_ON, status=TaskStatus.DONE,
    )
    db.add(task)
    db.flush()
    sample = MonitoringSample(project_id=project.id, task_id=task.id, attempt_no=1, status=SampleStatus.HIT, sampling_mode=SamplingMode.SEARCH_ON)
    db.add(sample)
    db.flush()
    return sample


def _add_citation(db, sample, *, url, domain, category=SourceCategory.UNKNOWN, status=CitationReviewStatus.MANUAL_CONFIRMED, title="标题", snippet="摘要"):
    citation = MonitoringCitation(
        project_id=sample.project_id, sample_id=sample.id, raw_url=url, normalized_url=url, domain=domain,
        title=title, snippet=snippet, source_category=category, page_type=CitationPageType.ARTICLE,
        review_status=status,
    )
    db.add(citation)
    db.flush()
    return citation


def test_sentiment_summary_and_credibility_order(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sent-{suffix}")
    editor = user_factory(f"sent-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    sample = _seed_sample(db, project)

    gov = _add_citation(db, sample, url="https://gov.example/a", domain="gov.example", category=SourceCategory.GOVERNMENT_INSTITUTION, title="官方发布")
    social = _add_citation(db, sample, url="https://social.example/b", domain="social.example", category=SourceCategory.SOCIAL_COMMUNITY, title="网友讨论")
    pending = _add_citation(db, sample, url="https://pending.example/c", domain="pending.example", status=CitationReviewStatus.AUTO)
    db.commit()

    base = f"/api/v1/projects/{project.id}/sentiment"

    summary = client.get(f"{base}/summary", headers=_auth(editor))
    assert summary.status_code == 200, summary.text
    data = summary.json()["data"]
    # 只统计人工复核通过的引用；auto 的不进分母
    assert data["total_reviewed_citations"] == 2
    assert data["unlabeled"] == 2
    assert data["counts"] == {"positive": 0, "neutral": 0, "negative": 0}
    assert data["coverage"] == 0

    items = client.get(f"{base}/items", headers=_auth(editor))
    assert items.status_code == 200, items.text
    rows = items.json()["data"]
    # 可信度排序：官方机构在社交/UGC 之前
    assert [row["domain"] for row in rows] == ["gov.example", "social.example"]
    assert rows[0]["credibility_score"] == 5
    assert rows[1]["credibility_score"] == 1

    labeled = client.post(
        f"{base}/{gov.id}/label",
        json={"polarity": "positive", "note": "官方通稿肯定基地"},
        headers=_auth(editor),
    )
    assert labeled.status_code == 200, labeled.text
    assert labeled.json()["data"]["polarity"] == "positive"

    summary2 = client.get(f"{base}/summary", headers=_auth(editor)).json()["data"]
    assert summary2["counts"]["positive"] == 1
    assert summary2["labeled"] == 1
    assert summary2["unlabeled"] == 1

    # 重复标注是覆盖而不是新增
    again = client.post(f"{base}/{gov.id}/label", json={"polarity": "neutral"}, headers=_auth(editor))
    assert again.status_code == 200
    summary3 = client.get(f"{base}/summary", headers=_auth(editor)).json()["data"]
    assert summary3["counts"]["positive"] == 0
    assert summary3["counts"]["neutral"] == 1

    # 未复核通过的引用不能标注
    rejected = client.post(f"{base}/{pending.id}/label", json={"polarity": "negative"}, headers=_auth(editor))
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "citation_not_confirmed"

    # 只读角色不能标注
    viewer = user_factory(f"sent-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    denied = client.post(f"{base}/{social.id}/label", json={"polarity": "negative"}, headers=_auth(viewer))
    assert denied.status_code == 403


def test_two_reviewers_can_label_same_citation_and_form_consensus(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sent2-{suffix}")
    first = user_factory(f"sent2-a-{suffix}")
    second = user_factory(f"sent2-b-{suffix}")
    member_factory(project, first, RoleCode.EDITOR)
    member_factory(project, second, RoleCode.EDITOR)
    sample = _seed_sample(db, project)
    citation = _add_citation(
        db, sample, url="https://gov2.example/a", domain="gov2.example",
        category=SourceCategory.GOVERNMENT_INSTITUTION, title="官方通稿",
    )
    db.commit()

    base = f"/api/v1/projects/{project.id}/sentiment"
    assert client.post(
        f"{base}/{citation.id}/label", json={"polarity": "positive"}, headers=_auth(first)
    ).status_code == 200
    assert client.post(
        f"{base}/{citation.id}/label", json={"polarity": "positive"}, headers=_auth(second)
    ).status_code == 200

    queue = client.get(f"{base}/sampling?size=12", headers=_auth(first)).json()["data"]
    matched = next(item for item in queue["sample"] if item["citation_id"] == str(citation.id))
    assert matched["label_count"] == 2

    consensus = client.get(f"{base}/consensus?size=12", headers=_auth(first)).json()["data"]
    assert consensus["consensus_total"] == 1
    assert consensus["counts"]["positive"] == 1
    # 人数够了但总量不足 50：只报条数，不报正向率
    assert consensus["positive_rate"] is None
    assert consensus["reportable"] is False


def test_negative_label_can_spawn_corrective_batch_once(
    client, db, project_factory, user_factory, member_factory
):
    """负面标注的处置闭环：引用 → 纠正批次，且同一引用只建一次。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sent3-{suffix}")
    editor = user_factory(f"sent3-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    sample = _seed_sample(db, project)
    negative = _add_citation(
        db, sample, url="https://bad.example/a", domain="bad.example",
        category=SourceCategory.SOCIAL_COMMUNITY, title="负面说法", snippet="据说该基地设备全部不合格",
    )
    positive = _add_citation(
        db, sample, url="https://gov3.example/b", domain="gov3.example",
        category=SourceCategory.GOVERNMENT_INSTITUTION, title="官方通稿",
    )
    db.commit()

    base = f"/api/v1/projects/{project.id}/sentiment"
    # 没标负面之前不能建纠正批次
    early = client.post(f"{base}/{negative.id}/corrective-batch", headers=_auth(editor))
    assert early.status_code == 400
    assert early.json()["error"]["code"] == "citation_not_negative"

    assert client.post(
        f"{base}/{negative.id}/label",
        json={"polarity": "negative", "note": "表述与官方验收结论不符"},
        headers=_auth(editor),
    ).status_code == 200

    created = client.post(
        f"{base}/{negative.id}/corrective-batch",
        json={"note": "按验收报告澄清"},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["source"] == "remediation"
    assert data["reused"] is False
    assert data["totals"]["total"] == 1
    item = data["items"][0]
    assert item["brief"]["citation_id"] == str(negative.id)
    assert item["brief"]["evidence_refs"][0]["domain"] == "bad.example"

    # 同一引用再来一次 → 复用，不新增批次
    again = client.post(f"{base}/{negative.id}/corrective-batch", headers=_auth(editor)).json()["data"]
    assert again["reused"] is True
    assert again["batch_id"] == data["batch_id"]
    batches = client.get(
        f"/api/v1/projects/{project.id}/generation-batches", headers=_auth(editor)
    ).json()["data"]
    assert len(batches) == 1

    # 出稿时正文不复述负面原文（避免二次传播），原文只留在证据条目
    ran = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{data['batch_id']}/run",
        headers=_auth(editor),
    )
    assert ran.status_code == 200, ran.text
    draft = ran.json()["data"]["items"][0]["draft_body"]
    assert "待澄清的说法" in draft
    assert "设备全部不合格" not in draft

    # 正面引文不能当纠正批次证据
    assert client.post(
        f"{base}/{positive.id}/label", json={"polarity": "negative"}, headers=_auth(editor)
    ).status_code == 200

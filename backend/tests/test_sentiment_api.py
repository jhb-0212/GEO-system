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

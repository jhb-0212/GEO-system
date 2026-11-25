"""自动机会建议：五条规则生成、人工采纳才建 Opportunity、处理过的不被重跑覆盖。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    AnswerFactClaim,
    Competitor,
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Opportunity,
    OpportunitySuggestion,
    PublicPage,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    AnswerKind,
    CitationReviewStatus,
    EngineEntryType,
    FactClaimVerdict,
    PagePublishStatus,
    PageType,
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


def _setup(db, project, editor):
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
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text="广州AI培训哪家好",
    )
    engine = AiEngine(
        code=f"eng-{uuid.uuid4().hex[:6]}",
        name="测试引擎",
        vendor="测试",
        supports_search=True,
        supports_citation=True,
        is_active=True,
    )
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        entry_type=EngineEntryType.API,
        name="测试入口",
        supports_search=True,
        is_active=True,
    )
    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="规则测试轮",
        is_baseline=False,
        status=RoundStatus.RUNNING,
    )
    db.add_all([version, entry, round_row])
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
        answer_kind=AnswerKind.ANSWER,
        brand_mentioned=True,
        brand_list_rank=4,
        brand_recommendation=False,
        recommendation_reason="list_rank_outside_top3",
        entity_mention_count=1,
        sampled_at=datetime.now(timezone.utc),
    )
    db.add(sample)
    db.flush()
    competitor = Competitor(
        project_id=project.id,
        name=f"竞品-{uuid.uuid4().hex[:4]}",
        is_active=True,
    )
    db.add(competitor)
    db.flush()
    db.add(
        MonitoringCompetitorMention(
            project_id=project.id,
            sample_id=sample.id,
            competitor_id=competitor.id,
            position=1,
        )
    )
    for index in range(3):
        db.add(
            MonitoringCitation(
                project_id=project.id,
                sample_id=sample.id,
                raw_url=f"https://media{index}.example.com/a",
                normalized_url=f"https://media{index}.example.com/a",
                domain=f"media{index}.example.com",
                title="行业媒体",
                is_brand_related=False,
                review_status=CitationReviewStatus.MANUAL_CONFIRMED,
            )
        )
    claim = AnswerFactClaim(
        project_id=project.id,
        sample_id=sample.id,
        claim_text="该机构成立于2012年",
        verdict=FactClaimVerdict.WRONG,
    )
    db.add(claim)
    # 第二个问题：两条有效回答都不提品牌，触发 brand_absent。
    question2 = Question(
        project_id=project.id,
        code=f"Q2-{uuid.uuid4().hex[:6]}",
        title="广州AI培训机构推荐",
        question_type=QuestionType.GENERAL,
        audience="广州",
        intent="找推荐",
        priority=90,
        status=QuestionStatus.ACTIVE,
        current_version_no=1,
    )
    db.add(question2)
    db.flush()
    version2 = QuestionVersion(
        project_id=project.id,
        question_id=question2.id,
        version_no=1,
        text="广州AI培训机构推荐",
    )
    db.add(version2)
    db.flush()
    task2 = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version2.id,
        engine_entry_id=entry.id,
        sampling_no=2,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.DONE,
    )
    db.add(task2)
    db.flush()
    db.add(
        MonitoringSample(
            project_id=project.id,
            task_id=task2.id,
            attempt_no=1,
            status=SampleStatus.HIT,
            sampling_mode=SamplingMode.SEARCH_ON,
            answer_kind=AnswerKind.ANSWER,
            brand_mentioned=False,
            brand_recommendation=False,
            recommendation_reason="brand_absent",
            entity_mention_count=0,
            sampled_at=datetime.now(timezone.utc),
        )
    )
    page = PublicPage(
        project_id=project.id,
        slug=f"old-{uuid.uuid4().hex[:6]}",
        title="过期课程页",
        page_type=PageType.COURSE,
        url="https://example.com/old",
        publish_status=PagePublishStatus.PUBLISHED,
        last_published_at=datetime.now(timezone.utc) - timedelta(days=400),
    )
    db.add(page)
    db.commit()
    return question, sample, claim, page


def test_five_rules_generate_and_accept_creates_opportunity(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"rules-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"rules-editor-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    question, sample, claim, page = _setup(db, project, editor)

    response = client.post(
        f"/api/v1/projects/{project.id}/opportunities/suggestions/generate",
        json={},
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["created"] >= 5
    rules = {
        item["rule_code"]
        for item in client.get(
            f"/api/v1/projects/{project.id}/opportunities/suggestions",
            params={"status": "suggested", "page_size": 100},
            headers=_auth(editor),
        ).json()["data"]
    }
    assert {
        "brand_absent", "competitor_outrank", "source_gap", "fact_error", "stale_content"
    } <= rules

    suggestion = db.scalar(
        select(OpportunitySuggestion).where(
            OpportunitySuggestion.project_id == project.id,
            OpportunitySuggestion.rule_code == "brand_absent",
        )
    )
    assert suggestion is not None
    assert suggestion.status.value == "suggested"
    # 规则本身不创建 Opportunity
    assert db.scalar(select(Opportunity).where(Opportunity.project_id == project.id)) is None

    accepted = client.post(
        f"/api/v1/projects/{project.id}/opportunities/suggestions/{suggestion.id}/accept",
        json={"note": "运营确认"},
        headers=_auth(editor),
    )
    assert accepted.status_code == 200, accepted.text
    opportunity = db.scalar(select(Opportunity).where(Opportunity.project_id == project.id))
    assert opportunity is not None
    assert opportunity.title == suggestion.title
    assert opportunity.question_id == suggestion.question_id

    # 已采纳的建议不能被下一次规则重跑改回 suggested。
    again = client.post(
        f"/api/v1/projects/{project.id}/opportunities/suggestions/generate",
        json={},
        headers=_auth(editor),
    )
    assert again.status_code == 200, again.text
    db.refresh(suggestion)
    assert suggestion.status.value == "accepted"
    assert suggestion.accepted_opportunity_id == opportunity.id


def test_rule_suggestions_are_idempotent(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"rules-idem-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"rules-idem-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _setup(db, project, editor)

    first = client.post(
        f"/api/v1/projects/{project.id}/opportunities/suggestions/generate",
        json={},
        headers=_auth(editor),
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/v1/projects/{project.id}/opportunities/suggestions/generate",
        json={},
        headers=_auth(editor),
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["created"] == 0
    assert second.json()["data"]["updated"] >= 5


def test_dismissed_suggestion_is_not_regenerated(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"rules-dismiss-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"rules-dismiss-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _setup(db, project, editor)
    client.post(
        f"/api/v1/projects/{project.id}/opportunities/suggestions/generate",
        json={},
        headers=_auth(editor),
    )
    suggestion = db.scalar(
        select(OpportunitySuggestion).where(
            OpportunitySuggestion.project_id == project.id,
            OpportunitySuggestion.rule_code == "fact_error",
        )
    )
    dismissed = client.post(
        f"/api/v1/projects/{project.id}/opportunities/suggestions/{suggestion.id}/dismiss",
        json={"note": "已线下处理"},
        headers=_auth(editor),
    )
    assert dismissed.status_code == 200, dismissed.text
    again = client.post(
        f"/api/v1/projects/{project.id}/opportunities/suggestions/generate",
        json={},
        headers=_auth(editor),
    )
    assert again.status_code == 200, again.text
    db.refresh(suggestion)
    assert suggestion.status.value == "dismissed"
    assert again.json()["data"]["skipped"] >= 1

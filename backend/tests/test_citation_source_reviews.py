"""引用来源分类与独立未知信源队列回归。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    AuditLog,
    Channel,
    CitationSourceReview,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    ChannelCategory,
    CitationUsage,
    EngineEntryType,
    QuestionStatus,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    SourceCategory,
    SourceReviewStatus,
    TaskStatus,
)
from app.services.citation_attribution import backfill_channel_for_url
from app.services.citation_classification import classify_citation
from app.services.monitoring_extraction import (
    AnswerPayload,
    CitationInput,
    apply_answer_payload,
)


def test_same_domain_can_have_homepage_and_article_page_types():
    home = classify_citation(domain="zhihu.com", url="https://zhihu.com/")
    article = classify_citation(
        domain="zhuanlan.zhihu.com", url="https://zhuanlan.zhihu.com/p/123"
    )
    assert home.page_type.value == "homepage"
    assert article.page_type.value == "article"



def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _make_sample(db, project: Project) -> MonitoringSample:
    suffix = uuid.uuid4().hex[:6]
    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="引用分类测试题",
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
        name="引用分类轮次",
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
        raw_answer="参考来源如下。",
    )
    db.add(sample)
    db.flush()
    return sample


def test_unknown_citation_enters_source_queue_and_keeps_provider_fields(db, project_factory):
    project = project_factory(f"src-{uuid.uuid4().hex[:6]}")
    sample = _make_sample(db, project)
    apply_answer_payload(
        db,
        sample,
        AnswerPayload(
            text="参考来源如下。",
            citations=[
                CitationInput(
                    url="https://zhuanlan.zhihu.com/p/12345",
                    title="广州实训基地怎么选",
                    position=2,
                    provider_fields={"provider": "test", "snippet": "原文"},
                )
            ],
        ),
    )
    db.flush()

    citation = db.scalar(select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id))
    assert citation.title == "广州实训基地怎么选"
    assert citation.position == 2
    assert citation.source_category == SourceCategory.SOCIAL_COMMUNITY
    assert citation.page_type is not None
    assert citation.provider_fields == {"provider": "test", "snippet": "原文"}

    review = db.scalar(
        select(CitationSourceReview).where(
            CitationSourceReview.project_id == project.id,
            CitationSourceReview.domain == "zhuanlan.zhihu.com",
        )
    )
    assert review is not None
    assert review.status == SourceReviewStatus.PENDING
    assert review.suggested_source_category == SourceCategory.SOCIAL_COMMUNITY


def test_manual_source_category_is_not_overwritten_by_later_auto_classification(
    db, client, project_factory, user_factory, member_factory
):
    project = project_factory(f"src-manual-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"src-editor-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.REVIEWER)
    sample = _make_sample(db, project)
    payload = AnswerPayload(
        text="参考来源如下。",
        citations=[CitationInput(url="https://www.example-news.com/a/1", usage=CitationUsage.CITED)],
    )
    apply_answer_payload(db, sample, payload)
    db.flush()
    review = db.scalar(
        select(CitationSourceReview).where(CitationSourceReview.project_id == project.id)
    )
    assert review is not None

    response = client.post(
        f"/api/v1/projects/{project.id}/citations/source-reviews/{review.id}/classify",
        json={"source_category": "news_media", "review_note": "人工确认为新闻媒体"},
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["source_category"] == "news_media"

    # 二次采集不能把人工分类改回规则结果
    apply_answer_payload(db, sample, payload)
    db.flush()
    citation = db.scalar(select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id))
    assert citation.source_category == SourceCategory.NEWS_MEDIA
    assert citation.classification_source.value == "manual"
    review = db.get(CitationSourceReview, review.id)
    assert review is not None
    assert review.status == SourceReviewStatus.CLASSIFIED
    assert review.source_category == SourceCategory.NEWS_MEDIA


def test_publish_receipt_backfill_only_matches_exact_url(db, project_factory):
    project = project_factory(f"src-backfill-{uuid.uuid4().hex[:6]}")
    sample = _make_sample(db, project)
    apply_answer_payload(
        db,
        sample,
        AnswerPayload(
            text="参考来源如下。",
            citations=[
                CitationInput(url="https://mp.weixin.qq.com/s/abc"),
                CitationInput(url="https://mp.weixin.qq.com/s/other"),
            ],
        ),
    )
    channel = Channel(
        project_id=project.id,
        code=f"ch-{uuid.uuid4().hex[:6]}",
        name="公众号",
        category=ChannelCategory.CONTENT_PLATFORM,
    )
    db.add(channel)
    db.flush()

    updated = backfill_channel_for_url(
        db, project.id, "https://mp.weixin.qq.com/s/abc?utm_source=receipt", channel.id
    )
    db.flush()
    rows = db.scalars(
        select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id)
    ).all()
    assert updated == 1
    assert sorted(row.channel_id == channel.id for row in rows) == [False, True]


def test_ignore_source_review_keeps_citation_and_records_audit(
    db, client, project_factory, user_factory, member_factory
):
    project = project_factory(f"src-ignore-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"src-reviewer-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _make_sample(db, project)
    apply_answer_payload(
        db,
        sample,
        AnswerPayload(
            text="参考来源如下。",
            citations=[CitationInput(url="https://ignore-source.example/x")],
        ),
    )
    db.flush()
    review = db.scalar(
        select(CitationSourceReview).where(
            CitationSourceReview.project_id == project.id,
            CitationSourceReview.domain == "ignore-source.example",
        )
    )
    assert review is not None

    response = client.post(
        f"/api/v1/projects/{project.id}/citations/source-reviews/{review.id}/ignore",
        headers=_auth(reviewer),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "ignored"

    citation = db.scalar(
        select(MonitoringCitation).where(
            MonitoringCitation.sample_id == sample.id,
            MonitoringCitation.domain == "ignore-source.example",
        )
    )
    assert citation is not None
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action == "citation.source_ignore",
            AuditLog.target_id == review.id,
        )
    )
    assert audit is not None


def test_source_review_queue_is_independent_from_channel_review_queue(
    client, project_factory, user_factory, member_factory, db
):
    project = project_factory(f"src-queue-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"src-viewer-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    sample = _make_sample(db, project)
    apply_answer_payload(
        db,
        sample,
        AnswerPayload(
            text="参考来源如下。",
            citations=[CitationInput(url="https://unknown-source.example/x")],
        ),
    )
    db.flush()

    response = client.get(
        f"/api/v1/projects/{project.id}/citations/source-reviews",
        headers=_auth(viewer),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert len(data) >= 1
    assert data[0]["domain"] == "unknown-source.example"
    assert data[0]["citation_count"] == 1

    # 历史渠道待归类队列保持原语义，不因未知引用域名自动增项
    channels = client.get(
        f"/api/v1/projects/{project.id}/citations/unknown-domains",
        headers=_auth(viewer),
    )
    assert channels.status_code == 200, channels.text
    assert channels.json()["meta"]["total"] == 0

"""统计口径与多维渠道导出的回归测试。"""

import csv
import io
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
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
    CitationReviewStatus,
    EngineEntryType,
    FailureCode,
    QuestionStatus,
    QuestionType,
    ReviewResult,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services import stats


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _make_fixture(db, project):
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(
        code=f"eng-{suffix}",
        name=f"测试引擎-{suffix}",
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
        name=f"网页端-{suffix}",
        supports_search=True,
        is_active=True,
    )
    db.add(entry)

    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="测试问题",
        question_type=QuestionType.BRAND,
        audience="零基础转行者",
        intent="了解课程",
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
        text="测试问题正文",
    )
    db.add(version)
    db.flush()

    channel = Channel(
        project_id=project.id,
        code=f"ch-{suffix}",
        name=f"测试渠道-{suffix}",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.OBSERVED,
        primary_domain="example.com",
    )
    db.add(channel)
    db.flush()

    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="基线轮次",
        is_baseline=True,
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

    sampled_at = datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)
    samples = [
        MonitoringSample(
            project_id=project.id,
            task_id=task.id,
            attempt_no=1,
            status=SampleStatus.HIT,
            sampled_at=sampled_at,
            sampling_mode=SamplingMode.SEARCH_ON,
            brand_mentioned=True,
            review_result=ReviewResult.HIT,
        ),
        MonitoringSample(
            project_id=project.id,
            task_id=task.id,
            attempt_no=2,
            status=SampleStatus.MISS,
            sampled_at=sampled_at,
            sampling_mode=SamplingMode.SEARCH_ON,
            brand_mentioned=False,
            review_result=ReviewResult.MISS,
        ),
        MonitoringSample(
            project_id=project.id,
            task_id=task.id,
            attempt_no=3,
            status=SampleStatus.FAILED,
            sampled_at=sampled_at,
            sampling_mode=SamplingMode.SEARCH_ON,
            failure_code=FailureCode.TIMEOUT,
            failure_note="测试超时",
        ),
        MonitoringSample(
            project_id=project.id,
            task_id=task.id,
            attempt_no=4,
            status=SampleStatus.MANUAL_REVIEW,
            sampled_at=sampled_at,
            sampling_mode=SamplingMode.SEARCH_ON,
            brand_mentioned=True,
        ),
    ]
    db.add_all(samples)
    db.flush()

    citation_a = MonitoringCitation(
        project_id=project.id,
        sample_id=samples[0].id,
        raw_url="https://example.com/a",
        normalized_url="https://example.com/a",
        domain="example.com",
        channel_id=channel.id,
        is_brand_related=True,
        review_status=CitationReviewStatus.MANUAL_CONFIRMED,
    )
    citation_b = MonitoringCitation(
        project_id=project.id,
        sample_id=samples[1].id,
        raw_url="https://example.com/a?utm=x",
        normalized_url="https://example.com/a",
        domain="example.com",
        channel_id=channel.id,
        is_brand_related=True,
        review_status=CitationReviewStatus.AUTO,
    )
    db.add_all([citation_a, citation_b])
    db.flush()
    return {
        "engine": engine,
        "entry": entry,
        "question": question,
        "version": version,
        "channel": channel,
        "round": round_row,
        "task": task,
        "samples": samples,
    }


def test_stats_overview_strict_denominator(db, project_factory):
    project = project_factory(f"stats-{uuid.uuid4().hex[:6]}")
    _make_fixture(db, project)

    result = stats.overview(db, project.id)

    assert result["valid_answers"] == 2
    assert result["brand_mentioned_answers"] == 1
    assert result["citation_answers"] == 1
    assert result["brand_mention_rate"] == 0.5
    assert result["citation_rate"] == 0.5
    assert result["channel_count"] == 1
    assert result["page_count"] == 1
    assert result["excluded"] == {"failed": 1, "manual_review": 1, "pending_or_running": 0}


def test_stats_returns_none_when_no_valid_answers(db, project_factory):
    project = project_factory(f"stats-empty-{uuid.uuid4().hex[:6]}")
    result = stats.overview(db, project.id)
    assert result["valid_answers"] == 0
    assert result["brand_mention_rate"] is None
    assert result["citation_rate"] is None
    assert result["channel_count"] == 0
    assert result["page_count"] == 0


def test_stats_by_engine_and_by_question(db, project_factory):
    project = project_factory(f"stats-group-{uuid.uuid4().hex[:6]}")
    fixture = _make_fixture(db, project)
    by_engine = stats.by_engine(db, project.id)
    by_question = stats.by_question(db, project.id)

    assert len(by_engine) == 1
    assert by_engine[0]["engine_id"] == str(fixture["engine"].id)
    assert by_engine[0]["valid_answers"] == 2
    assert by_engine[0]["brand_mention_rate"] == 0.5
    assert by_engine[0]["citation_rate"] == 0.5

    assert len(by_question) == 1
    assert by_question[0]["question_id"] == str(fixture["question"].id)
    assert by_question[0]["question_type"] == "brand"
    assert by_question[0]["valid_answers"] == 2


def test_channels_export_filtered_by_engine_question(
    client, db, project_factory, user_factory, member_factory
):
    from app.models.enums import RoleCode

    project = project_factory(f"export-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"viewer-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    fixture = _make_fixture(db, project)

    response = client.get(
        f"/api/v1/projects/{project.id}/channels/export",
        params={
            "engine_id": str(fixture["engine"].id),
            "question_id": str(fixture["question"].id),
            "start_date": "2026-11-11",
            "end_date": "2026-11-11",
        },
        headers=_auth(viewer),
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]

    content = response.content.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(content)))
    assert len(rows) == 1
    assert rows[0]["code"] == fixture["channel"].code
    assert rows[0]["citation_count"] == "2"
    assert rows[0]["sample_count"] == "2"
    assert rows[0]["page_count"] == "1"
    assert fixture["engine"].code in rows[0]["engine_codes"]
    assert fixture["question"].code in rows[0]["question_codes"]

    from app.models import AuditLog

    audit = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "export",
            AuditLog.project_id == project.id,
        )
    ).all()
    assert audit
    assert audit[-1].payload["filters"]["engine_id"] == str(fixture["engine"].id)
    assert audit[-1].payload["filters"]["question_id"] == str(fixture["question"].id)
    assert audit[-1].payload["row_count"] == 1


def test_channel_detail_returns_citations_and_page_dedup(
    client, db, project_factory, user_factory, member_factory
):
    from app.models.enums import RoleCode

    project = project_factory(f"detail-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"viewer-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    fixture = _make_fixture(db, project)

    response = client.get(
        f"/api/v1/projects/{project.id}/channels/{fixture['channel'].id}",
        headers=_auth(viewer),
    )
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["code"] == fixture["channel"].code
    assert data["citation_count"] == 2
    assert data["sample_count"] == 2
    assert data["page_count"] == 1
    assert data["page_urls"] == ["https://example.com/a"]
    assert data["engine_codes"] == [fixture["engine"].code]
    assert data["question_codes"] == [fixture["question"].code]
    assert len(data["citations"]) == 2
    assert data["citations"][0]["raw_url"].startswith("https://example.com/")
    assert data["citations"][0]["answer_excerpt"] is None
    assert {row["review_status"] for row in data["citations"]} == {
        "manual_confirmed",
        "auto",
    }


def test_channel_detail_empty_and_forbidden(
    client, db, project_factory, user_factory, member_factory
):
    from app.models.enums import ChannelCategory, ChannelStatus, RoleCode

    project = project_factory(f"detail-empty-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"viewer-{uuid.uuid4().hex[:6]}")
    outsider = user_factory(f"outsider-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    empty_channel = Channel(
        project_id=project.id,
        code=f"empty-{uuid.uuid4().hex[:6]}",
        name="无引用渠道",
        category=ChannelCategory.OWN_SITE,
        status=ChannelStatus.CANDIDATE,
        primary_domain="empty.example.com",
    )
    db.add(empty_channel)
    db.flush()

    response = client.get(
        f"/api/v1/projects/{project.id}/channels/{empty_channel.id}",
        headers=_auth(viewer),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["citation_count"] == 0
    assert data["sample_count"] == 0
    assert data["page_count"] == 0
    assert data["page_urls"] == []
    assert data["citations"] == []

    forbidden = client.get(
        f"/api/v1/projects/{project.id}/channels/{empty_channel.id}",
        headers=_auth(outsider),
    )
    assert forbidden.status_code == 403

    missing = client.get(
        f"/api/v1/projects/{project.id}/channels/{uuid.uuid4()}",
        headers=_auth(viewer),
    )
    assert missing.status_code == 404
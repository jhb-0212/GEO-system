"""B6 引用复核测试。

覆盖：reviewer 确认/驳回归属、editor 越权 403、跨项目 403、列表筛选、
未知域名待归类队列、手动回写 auto 被拒 400；归属改挂 channel_id / competitor_id
同项目改挂成功、跨项目 404、不存在 404、显式 null 清空映射。
"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    AuditLog,
    Channel,
    Competitor,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    CitationPageType,
    CitationReviewStatus,
    CitationUsage,
    ClassificationSource,
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


def _seed_sample(db, project) -> MonitoringSample:
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
        status=SampleStatus.HIT,
        sampling_mode=SamplingMode.SEARCH_ON,
    )
    db.add(sample)
    db.flush()
    return sample


def _add_citation(
    db, sample, *, url, domain, review_status=CitationReviewStatus.AUTO, channel_id=None
):
    citation = MonitoringCitation(
        project_id=sample.project_id,
        sample_id=sample.id,
        raw_url=url,
        normalized_url=url,
        domain=domain,
        citation_usage=CitationUsage.CITED,
        is_brand_related=False,
        review_status=review_status,
        channel_id=channel_id,
    )
    db.add(citation)
    db.flush()
    return citation


def test_reviewer_can_confirm_citation(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={"review_status": CitationReviewStatus.MANUAL_CONFIRMED.value, "review_note": "归属确认"},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["review_status"] == CitationReviewStatus.MANUAL_CONFIRMED.value

    db.refresh(citation)
    assert citation.review_status == CitationReviewStatus.MANUAL_CONFIRMED
    assert citation.reviewed_by == reviewer.id
    assert citation.reviewed_at is not None

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "citation.review",
            AuditLog.target_id == citation.id,
        )
    )
    assert audit is not None


def test_reviewer_can_override_citation_page_type(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"a8-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")
    citation.page_type = CitationPageType.ARTICLE
    citation.classification_source = ClassificationSource.RULE
    db.flush()

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}/page-type",
        json={"page_type": CitationPageType.FAQ.value},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["page_type"] == CitationPageType.FAQ.value
    assert data["classification_source"] == ClassificationSource.MANUAL.value
    assert data["classification_rule_version"] == "manual-page-type-v1"

    db.refresh(citation)
    assert citation.page_type == CitationPageType.FAQ
    assert citation.classification_source == ClassificationSource.MANUAL
    assert citation.classification_rule_version == "manual-page-type-v1"

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "citation.page_type_override",
            AuditLog.target_id == citation.id,
        )
    )
    assert audit is not None
    assert audit.payload["page_type_from"] == CitationPageType.ARTICLE.value
    assert audit.payload["page_type_to"] == CitationPageType.FAQ.value


def test_editor_cannot_review_citation(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={"review_status": CitationReviewStatus.MANUAL_REJECTED.value},
        headers=_auth(editor),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "insufficient_permission"


def test_cross_project_citation_forbidden(
    client, db, project_factory, user_factory, member_factory
):
    p1 = project_factory(f"b6a-{uuid.uuid4().hex[:6]}")
    p2 = project_factory(f"b6b-{uuid.uuid4().hex[:6]}")
    outsider = user_factory(f"out-{uuid.uuid4().hex[:6]}")
    member_factory(p2, outsider, RoleCode.REVIEWER)
    sample = _seed_sample(db, p1)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")

    resp = client.patch(
        f"/api/v1/projects/{p2.id}/citations/{citation.id}",
        json={"review_status": CitationReviewStatus.MANUAL_CONFIRMED.value},
        headers=_auth(outsider),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "project_forbidden"


def test_list_citations_filter_by_status(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"vw-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    sample = _seed_sample(db, project)
    confirmed = _add_citation(
        db, sample, url="https://example.com/a", domain="example.com",
        review_status=CitationReviewStatus.MANUAL_CONFIRMED,
    )
    _add_citation(db, sample, url="https://other.com/b", domain="other.com")

    resp = client.get(
        f"/api/v1/projects/{project.id}/citations",
        params={"review_status": CitationReviewStatus.MANUAL_CONFIRMED.value},
        headers=_auth(viewer),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["citation_id"] == str(confirmed.id)


def test_unknown_domains_queue_lists_review_pending_channels(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    sample = _seed_sample(db, project)

    pending = Channel(
        project_id=project.id,
        code=f"unk-{uuid.uuid4().hex[:6]}",
        name="待归类渠道",
        category=ChannelCategory.COMMUNITY,
        status=ChannelStatus.REVIEW_PENDING,
        primary_domain="unknown-1.edge.example",
    )
    db.add(pending)
    db.flush()
    settled = Channel(
        project_id=project.id,
        code=f"ok-{uuid.uuid4().hex[:6]}",
        name="已归类渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.PUBLISHED,
        primary_domain="example.com",
    )
    db.add(settled)
    db.flush()

    _add_citation(
        db, sample, url="https://unknown-1.edge.example/x",
        domain="unknown-1.edge.example", channel_id=pending.id,
    )
    _add_citation(
        db, sample, url="https://example.com/a",
        domain="example.com", channel_id=settled.id,
    )

    resp = client.get(
        f"/api/v1/projects/{project.id}/citations/unknown-domains",
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]
    assert len(items) == 1
    assert items[0]["channel_id"] == str(pending.id)
    assert items[0]["citation_count"] == 1
    assert items[0]["sample_count"] == 1


def test_patch_reject_auto_status(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={"review_status": CitationReviewStatus.AUTO.value},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_review_status"


def _add_channel(db, project, *, status=ChannelStatus.REVIEW_PENDING):
    channel = Channel(
        project_id=project.id,
        code=f"ch-{uuid.uuid4().hex[:6]}",
        name="渠道",
        category=ChannelCategory.COMMUNITY,
        status=status,
        approval_status=ChannelApprovalStatus.APPROVED,
    )
    db.add(channel)
    db.flush()
    return channel


def _add_competitor(db, project):
    competitor = Competitor(
        project_id=project.id,
        name=f"竞品-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    db.add(competitor)
    db.flush()
    return competitor


def test_reassign_channel_within_project_ok(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")
    channel = _add_channel(db, project)

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_CONFIRMED.value,
            "channel_id": str(channel.id),
        },
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["channel_id"] == str(channel.id)
    db.refresh(citation)
    assert citation.channel_id == channel.id


def test_reassign_channel_other_project_404(client, db, project_factory, user_factory, member_factory):
    p1 = project_factory(f"b6a-{uuid.uuid4().hex[:6]}")
    p2 = project_factory(f"b6b-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(p1, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, p1)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")
    other_channel = _add_channel(db, p2)

    resp = client.patch(
        f"/api/v1/projects/{p1.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_CONFIRMED.value,
            "channel_id": str(other_channel.id),
        },
        headers=_auth(reviewer),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "resource_missing"


def test_reassign_missing_channel_404(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_CONFIRMED.value,
            "channel_id": str(uuid.uuid4()),
        },
        headers=_auth(reviewer),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "resource_missing"


def test_clear_channel_mapping_with_null(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    channel = _add_channel(db, project)
    citation = _add_citation(
        db, sample, url="https://example.com/a", domain="example.com", channel_id=channel.id
    )

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_REJECTED.value,
            "channel_id": None,
        },
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["channel_id"] is None
    db.refresh(citation)
    assert citation.channel_id is None


def test_reassign_competitor_within_project_ok(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")
    competitor = _add_competitor(db, project)

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_CONFIRMED.value,
            "competitor_id": str(competitor.id),
        },
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["competitor_id"] == str(competitor.id)
    db.refresh(citation)
    assert citation.competitor_id == competitor.id


def test_reassign_competitor_other_project_404(client, db, project_factory, user_factory, member_factory):
    p1 = project_factory(f"b6a-{uuid.uuid4().hex[:6]}")
    p2 = project_factory(f"b6b-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(p1, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, p1)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")
    other_competitor = _add_competitor(db, p2)

    resp = client.patch(
        f"/api/v1/projects/{p1.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_CONFIRMED.value,
            "competitor_id": str(other_competitor.id),
        },
        headers=_auth(reviewer),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "resource_missing"


def test_reassign_competitor_missing_404(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_CONFIRMED.value,
            "competitor_id": str(uuid.uuid4()),
        },
        headers=_auth(reviewer),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "resource_missing"


def test_clear_competitor_mapping_with_null(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    competitor = _add_competitor(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")
    citation.competitor_id = competitor.id
    db.flush()

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_REJECTED.value,
            "competitor_id": None,
        },
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["competitor_id"] is None
    db.refresh(citation)
    assert citation.competitor_id is None


def test_patch_without_note_keeps_existing_note(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")
    citation.review_note = "原有备注"
    db.flush()

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={"review_status": CitationReviewStatus.MANUAL_CONFIRMED.value},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    db.refresh(citation)
    assert citation.review_note == "原有备注"


def test_patch_note_null_clears_note(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"b6-{uuid.uuid4().hex[:6]}")
    reviewer = user_factory(f"rv-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample, url="https://example.com/a", domain="example.com")
    citation.review_note = "待清空备注"
    db.flush()

    resp = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_CONFIRMED.value,
            "review_note": None,
        },
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["review_note"] is None
    db.refresh(citation)
    assert citation.review_note is None

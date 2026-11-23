"""分发侧三项：页面三态、渠道×引擎矩阵、分发候选。

统一用构造数据验证口径：三态不合成分数、矩阵只按被引条数排序、候选只列 approved。
"""

import uuid
from datetime import UTC, datetime

from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    ContentItem,
    ContentVersion,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    PublishAccount,
    PublishReceipt,
    PublishTask,
    PublishVisibilityCheck,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    CitationPageType,
    CitationReviewStatus,
    ContentKind,
    ContentStatus,
    EngineEntryType,
    PublishMode,
    PublishTaskStatus,
    QuestionType,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    SourceCategory,
    TaskStatus,
)
from app.services.distribution_advice import (
    channel_candidates,
    confirm_engine_targets,
    engine_target_matrix,
)
from app.services.page_visibility import page_visibility


def _channel(db, project, name, *, approved=True):
    channel = Channel(
        project_id=project.id, code=f"ch-{uuid.uuid4().hex[:8]}", name=name,
        category=ChannelCategory.CONTENT_PLATFORM, status=ChannelStatus.PUBLISHED,
        approval_status=ChannelApprovalStatus.APPROVED if approved else ChannelApprovalStatus.PENDING_REVIEW,
    )
    db.add(channel)
    db.flush()
    db.add(PublishAccount(project_id=project.id, channel_id=channel.id, account_name=f"账号-{name}"))
    db.flush()
    return channel


def _engine_sample(db, project):
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"eng-{suffix}", name="测试引擎", vendor="测试",
                      supports_search=True, supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    question = Question(project_id=project.id, code=f"Q-{suffix}", title="题", question_type=QuestionType.GENERAL,
                        status="active", current_version_no=1)
    db.add_all([entry, question])
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="轮次", status=RoundStatus.RUNNING)
    db.add_all([version, round_row])
    db.flush()
    task = MonitoringTask(project_id=project.id, round_id=round_row.id, question_version_id=version.id,
                          engine_entry_id=entry.id, sampling_no=1, sampling_mode=SamplingMode.SEARCH_ON,
                          status=TaskStatus.DONE)
    db.add(task)
    db.flush()
    sample = MonitoringSample(project_id=project.id, task_id=task.id, attempt_no=1,
                              status=SampleStatus.HIT, sampled_at=datetime.now(UTC), brand_mentioned=True)
    db.add(sample)
    db.flush()
    return engine, sample


def _published(db, project, channel, url):
    master = ContentItem(project_id=project.id, title="母稿", kind=ContentKind.MASTER, status=ContentStatus.PUBLISHED)
    db.add(master)
    db.flush()
    item = ContentItem(project_id=project.id, title="渠道稿", kind=ContentKind.CHANNEL,
                       status=ContentStatus.PUBLISHED, parent_id=master.id, channel_id=channel.id)
    db.add(item)
    db.flush()
    version = ContentVersion(project_id=project.id, item_id=item.id, version_no=1, body="正文",
                             content_hash=uuid.uuid4().hex.ljust(64, "0"), status=ContentStatus.PUBLISHED)
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    account = db.query(PublishAccount).filter_by(channel_id=channel.id).first()
    task = PublishTask(project_id=project.id, version_id=version.id, channel_id=channel.id,
                       account_id=account.id, task_key=uuid.uuid4().hex[:16],
                       idempotency_key=uuid.uuid4().hex[:16], publish_mode=PublishMode.MANUAL,
                       status=PublishTaskStatus.PUBLISHED)
    db.add(task)
    db.flush()
    receipt = PublishReceipt(project_id=project.id, task_id=task.id, published_url=url,
                             received_at=datetime.now(UTC))
    db.add(receipt)
    db.flush()
    return task, receipt, version


def test_page_visibility_keeps_three_states_separate(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"pv-{suffix}")
    channel = _channel(db, project, f"渠道-{suffix}")
    engine, sample = _engine_sample(db, project)
    url = "https://example.com/page-a"
    task, receipt, version = _published(db, project, channel, url)

    receipt.last_reachable = True
    receipt.last_reachability_status = 200
    receipt.last_reachability_at = datetime.now(UTC)
    db.add(PublishVisibilityCheck(project_id=project.id, receipt_id=receipt.id, checked_at=datetime.now(UTC),
                                  matched=True, position=3, query="示例查询", result_count=5))
    db.add(MonitoringCitation(
        project_id=project.id, sample_id=sample.id, raw_url=url, normalized_url=url,
        domain="example.com", title="渠道稿", page_type=CitationPageType.ARTICLE, page_type_source="rule",
        source_category=SourceCategory.CONTENT_PLATFORM, channel_id=channel.id,
        review_status=CitationReviewStatus.MANUAL_CONFIRMED, is_brand_related=True,
    ))
    db.commit()

    report = page_visibility(db, project.id)
    page = next(p for p in report["pages"] if p["receipt_id"] == str(receipt.id))
    assert page["accessible"] == "yes"
    assert page["searchable"] == "yes"
    assert page["cited"] == 1
    assert page["channel"] == f"渠道-{suffix}"
    assert report["summary"]["cited_pages"] == 1
    # 未观测的态必须是 unknown，不能写成 no
    assert page["searchable_detail"].startswith("第 3 位")


def test_page_visibility_unknown_when_not_checked(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"pv2-{suffix}")
    channel = _channel(db, project, f"渠道2-{suffix}")
    _, receipt, _ = _published(db, project, channel, "https://example.com/page-b")
    db.commit()
    page = next(p for p in page_visibility(db, project.id)["pages"] if p["receipt_id"] == str(receipt.id))
    assert page["accessible"] == "unknown"
    assert page["searchable"] == "unknown"
    assert page["cited"] == 0


def test_engine_target_matrix_and_candidates(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"et-{suffix}")
    channel_a = _channel(db, project, f"A-{suffix}")
    channel_b = _channel(db, project, f"B-{suffix}")
    channel_pending = _channel(db, project, f"P-{suffix}", approved=False)
    engine, sample = _engine_sample(db, project)

    for index in range(2):
        db.add(MonitoringCitation(
            project_id=project.id, sample_id=sample.id, raw_url=f"https://example.com/a{index}",
            normalized_url=f"https://example.com/a{index}", domain="example.com", title="A 稿",
            page_type=CitationPageType.ARTICLE, page_type_source="rule",
            source_category=SourceCategory.CONTENT_PLATFORM, channel_id=channel_a.id,
            review_status=CitationReviewStatus.MANUAL_CONFIRMED, is_brand_related=True,
        ))
    db.add(MonitoringCitation(
        project_id=project.id, sample_id=sample.id, raw_url="https://example.com/b0",
        normalized_url="https://example.com/b0", domain="example.com", title="B 稿",
        page_type=CitationPageType.ARTICLE, page_type_source="rule",
        source_category=SourceCategory.CONTENT_PLATFORM, channel_id=channel_pending.id,
        review_status=CitationReviewStatus.MANUAL_CONFIRMED, is_brand_related=True,
    ))
    db.commit()

    matrix = engine_target_matrix(db, project.id)
    row_a = next(r for r in matrix["rows"] if r["channel_id"] == str(channel_a.id))
    assert row_a["cited"] == 2
    assert row_a["engine_code"] == engine.code
    assert row_a["confirmed_priority"] is None

    confirmed = confirm_engine_targets(db, project.id, [
        {"channel_code": channel_a.code, "engine_code": engine.code, "priority": 1, "note": "该引擎引用最多"}
    ])
    assert confirmed["changed"] == 1
    matrix2 = engine_target_matrix(db, project.id)
    row_a2 = next(r for r in matrix2["rows"] if r["channel_id"] == str(channel_a.id))
    assert row_a2["confirmed_priority"] == 1

    candidates = channel_candidates(db, project.id)
    names = [row["channel"] for row in candidates["candidates"]]
    assert f"A-{suffix}" in names
    assert f"P-{suffix}" not in names  # pending_review 不进候选
    assert all(row["approval_status"] == "approved" for row in candidates["candidates"])
    top = candidates["candidates"][0]
    assert top["channel"] == f"A-{suffix}"
    assert top["cited"] == 2

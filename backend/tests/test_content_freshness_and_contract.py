"""内容新鲜度 + 验收契约：口径要能被追问。

钉住五条：
1. 新鲜度只认发布回执时间，任务标 published 但没回执的单列 published_unverified；
2. 18 个月窗口外标 stale，窗口内 fresh，未发布不进新鲜度分母；
3. 渠道维度按渠道聚合，未挂渠道的单独成组；
4. 验收契约三个率分母都是有效回答，未标注情感时正向率为空且标 not_collected；
5. 连续采集天数从今天往回数，断一天即归零。
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.security import create_access_token
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
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    SourceCategory,
    TaskStatus,
)
from app.services.content_freshness import freshness_report


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _channel(db, project, name):
    channel = Channel(
        project_id=project.id, code=f"ch-{uuid.uuid4().hex[:8]}", name=name,
        category=ChannelCategory.CONTENT_PLATFORM, status=ChannelStatus.PUBLISHED,
        approval_status=ChannelApprovalStatus.APPROVED,
    )
    db.add(channel)
    db.flush()
    db.add(PublishAccount(project_id=project.id, channel_id=channel.id, account_name=f"账号-{name}"))
    db.flush()
    return channel


def _published_copy(db, project, title, channel, published_at, *, with_receipt=True):
    """母稿 + 一份渠道稿 + 一条发布任务（可选回执）。"""
    master = ContentItem(project_id=project.id, title=f"{title}-母稿", kind=ContentKind.MASTER, status=ContentStatus.PUBLISHED)
    db.add(master)
    db.flush()
    item = ContentItem(project_id=project.id, title=title, kind=ContentKind.CHANNEL, status=ContentStatus.PUBLISHED,
                       parent_id=master.id, channel_id=channel.id)
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
    if with_receipt:
        db.add(PublishReceipt(project_id=project.id, task_id=task.id, published_url="https://example.com/x",
                              received_at=published_at))
    db.flush()
    return item, version


def test_freshness_report(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"fresh-{suffix}")
    now = datetime.now(UTC)
    channel = _channel(db, project, f"渠道-{suffix}")

    _published_copy(db, project, "新稿", channel, now - timedelta(days=10))
    _published_copy(db, project, "老稿", channel, now - timedelta(days=700))
    _published_copy(db, project, "标了发布但没回执", channel, now - timedelta(days=5), with_receipt=False)
    # 一条完全没有发布动作的母稿
    db.add(ContentItem(project_id=project.id, title="没发出去的稿", kind=ContentKind.MASTER, status=ContentStatus.DRAFT))
    db.commit()

    report = freshness_report(db, project.id, months=18, now=now)
    assert report["summary"]["total"] == 7  # 3 份母稿 + 3 份渠道稿 + 1 条草稿母稿
    assert report["summary"]["fresh"] == 1
    assert report["summary"]["stale"] == 1
    assert report["summary"]["published_unverified"] == 1
    assert report["summary"]["stale_rate"] == 0.5

    channel_row = report["by_channel"][0]
    assert channel_row["channel_name"] == channel.name
    assert channel_row["stale"] == 1
    assert channel_row["stale_rate"] == 0.5

    first = report["items"][0]
    assert first["title"] == "老稿"
    assert first["status"] == "stale"
    assert first["age_days"] >= 690


def test_freshness_boundary(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"fresh-b-{suffix}")
    now = datetime.now(UTC)
    channel = _channel(db, project, f"b-{suffix}")
    _published_copy(db, project, "十七个月", channel, now - timedelta(days=520))
    db.commit()
    def status_of(report):
        return next(row["status"] for row in report["items"] if row["title"] == "十七个月")

    assert status_of(freshness_report(db, project.id, months=18, now=now)) == "fresh"
    assert status_of(freshness_report(db, project.id, months=17, now=now)) == "stale"


def test_acceptance_contract_rates_and_streak(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"ac-{suffix}")
    viewer = user_factory(f"ac-v-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    engine = AiEngine(code=f"ac-{suffix}", name="契约引擎", vendor="测试", supports_search=True,
                      supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    db.add(entry)
    question = Question(project_id=project.id, code=f"AC-{suffix}", title="契约题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="契约题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="契约轮次", status=RoundStatus.RUNNING)
    db.add_all([version, round_row])
    db.flush()

    # 今天 2 条（1 提及+引用、1 未提及），昨天 1 条提及，前天断档
    now = datetime.now(UTC)
    offsets = [(0, True, True), (0, False, False), (1, True, False)]
    for index, (day_offset, mentioned, cited) in enumerate(offsets):
        task = MonitoringTask(project_id=project.id, round_id=round_row.id, question_version_id=version.id,
                              engine_entry_id=entry.id, sampling_no=index + 1,
                              sampling_mode=SamplingMode.SEARCH_ON, status=TaskStatus.DONE)
        db.add(task)
        db.flush()
        sample = MonitoringSample(project_id=project.id, task_id=task.id, attempt_no=1,
                                 status=SampleStatus.HIT,
                                 sampled_at=now - timedelta(days=day_offset), brand_mentioned=mentioned)
        db.add(sample)
        db.flush()
        if cited:
            db.add(MonitoringCitation(
                project_id=project.id, sample_id=sample.id,
                raw_url="https://example.com/ac", normalized_url="https://example.com/ac", domain="example.com",
                page_type=CitationPageType.ARTICLE, page_type_source="rule",
                source_category=SourceCategory.SOCIAL_COMMUNITY,
                review_status=CitationReviewStatus.MANUAL_CONFIRMED, is_brand_related=True,
            ))
    db.commit()

    data = client.get(
        f"/api/v1/projects/{project.id}/stats/acceptance-contract?days=30&target_streak=2",
        headers=_auth(viewer),
    ).json()["data"]
    assert data["valid_answers"] == 3
    assert data["rates"]["mention_rate"] == round(2 / 3, 4)
    assert data["rates"]["citation_rate"] == round(1 / 3, 4)
    # 没有情感标注：正向率为空，不填 0
    assert data["rates"]["positive_rate"] is None
    assert data["ready"]["missing"] == ["positive_rate"]
    assert data["ready"]["contract_ok"] is False
    # 今天 + 昨天连续 2 天，前天断档
    assert data["streak"]["days"] == 2
    assert data["streak"]["ok"] is True

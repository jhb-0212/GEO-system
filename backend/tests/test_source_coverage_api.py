"""M1 引用源覆盖：Top N 站点里我们占几个、缺哪些。

钉住四条：
1. 只算已复核引用，未复核不进分母；
2. 覆盖率分母固定为 Top N，明确不是全网域名；
3. 自有域名命中算覆盖，有发布回执落在该域名也算覆盖；
4. 缺口只列「竞品被引 + 我们没发过 + 不是自有域名」的站。
"""

import uuid
from datetime import UTC, datetime

from app.core.security import create_access_token
from datetime import timezone

from app.models import (
    AiEngine,
    AiEngineEntry,
    BrandProfile,
    Channel,
    Competitor,
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
    ChannelCategory,
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


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _seed(db, project):
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"m1-{suffix}", name="M1 引擎", vendor="测试", supports_search=True,
                      supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    db.add(entry)
    question = Question(project_id=project.id, code=f"M1-{suffix}", title="M1 品类题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="M1 品类题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="M1 轮次", status=RoundStatus.RUNNING)
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

    db.add(BrandProfile(project_id=project.id, canonical_name="本品牌", owned_domains=["gdccai.com"]))
    channel = Channel(project_id=project.id, code=f"ch-{suffix}", name="头条号",
                      category=ChannelCategory.CONTENT_PLATFORM, primary_domain="toutiao.com")
    db.add(channel)
    db.flush()
    rival = Competitor(project_id=project.id, name="竞品甲", is_active=True)
    db.add(rival)
    db.flush()

    citations = [
        # 自家域名：算覆盖
        ("gdccai.com", SourceCategory.BRAND_OWNED, None, CitationReviewStatus.MANUAL_CONFIRMED),
        # 我方发过内容：算覆盖
        ("toutiao.com", SourceCategory.CONTENT_PLATFORM, None, CitationReviewStatus.MANUAL_CONFIRMED),
        # 竞品被引、我们没发：缺口
        ("zhihu.com", SourceCategory.SOCIAL_COMMUNITY, rival.id, CitationReviewStatus.MANUAL_CONFIRMED),
        # 未复核：不进分母
        ("weibo.com", SourceCategory.SOCIAL_COMMUNITY, None, CitationReviewStatus.AUTO),
    ]
    for domain, category, competitor_id, review in citations:
        db.add(MonitoringCitation(
            project_id=project.id, sample_id=sample.id,
            raw_url=f"https://{domain}/a/{suffix}", normalized_url=f"{domain}/a/{suffix}",
            domain=domain, is_brand_related=domain == "gdccai.com",
            source_category=category, competitor_id=competitor_id, review_status=review,
        ))
    # 头条有发布回执 → 判为已覆盖
    account = PublishAccount(project_id=project.id, channel_id=channel.id, account_name="头条账号")
    db.add(account)
    db.flush()
    item = ContentItem(project_id=project.id, kind=ContentKind.MASTER, title=f"覆盖稿-{suffix}",
                       status=ContentStatus.APPROVED)
    db.add(item)
    db.flush()
    content_version = ContentVersion(project_id=project.id, item_id=item.id, version_no=1, body="正文",
                                     content_hash=uuid.uuid4().hex, status=ContentStatus.APPROVED)
    db.add(content_version)
    db.flush()
    publish_task = PublishTask(project_id=project.id, version_id=content_version.id, channel_id=channel.id,
                               account_id=account.id, task_key=f"key-{suffix}", idempotency_key=f"idem-{suffix}",
                               publish_mode=PublishMode.MANUAL, status=PublishTaskStatus.PUBLISHED)
    db.add(publish_task)
    db.flush()
    db.add(PublishReceipt(project_id=project.id, task_id=publish_task.id,
                          published_url=f"https://www.toutiao.com/item/{suffix}",
                          received_at=datetime.now(timezone.utc)))
    db.flush()


def test_source_coverage_counts_owned_and_gaps(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"m1-{suffix}")
    viewer = user_factory(f"m1-v-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    _seed(db, project)

    response = client.get(
        f"/api/v1/projects/{project.id}/stats/source-coverage?days=90&limit=20",
        headers=_auth(viewer),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    # 4 条引用里只有 3 条已复核（weibo 是 auto）
    assert data["scope"]["reviewed_citations"] == 3
    assert data["coverage"]["top_domains"] == 3
    assert data["coverage"]["owned_domains"] == 1
    assert data["coverage"]["covered_domains"] == 2
    assert data["coverage"]["covered_rate"] == round(2 / 3, 4)

    by_domain = {row["domain"]: row for row in data["domains"]}
    assert by_domain["gdccai.com"]["owned_by_us"] is True
    assert by_domain["toutiao.com"]["our_publications"] == 1
    assert by_domain["zhihu.com"]["competitor_citations"] == 1

    gaps = {row["domain"]: row for row in data["gaps"]}
    assert "zhihu.com" in gaps
    assert gaps["zhihu.com"]["competitor_names"] == ["竞品甲"]
    assert "toutiao.com" not in gaps  # 我们发过，不算缺口
    assert "weibo.com" not in by_domain  # 未复核不进分母


def test_source_coverage_empty_project_returns_nulls(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"m1-empty-{suffix}")
    viewer = user_factory(f"m1-empty-v-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    response = client.get(
        f"/api/v1/projects/{project.id}/stats/source-coverage", headers=_auth(viewer)
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scope"]["reviewed_citations"] == 0
    assert data["coverage"]["owned_rate"] is None
    assert data["domains"] == []
    assert data["gaps"] == []
    assert len(data["notes"]) == 3

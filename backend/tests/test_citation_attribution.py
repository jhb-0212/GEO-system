"""引用归因回归：只认发布回执 URL，不按域名认渠道；信源分布与渠道效果分开算。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    ChannelAlias,
    ContentItem,
    ContentVersion,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    PublishAccount,
    PublishReceipt,
    PublishTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    ChannelCategory,
    ChannelStatus,
    CitationUsage,
    ContentKind,
    ContentStatus,
    EngineEntryType,
    ProjectStatus,
    QuestionStatus,
    QuestionType,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.citation_attribution import (
    backfill_project_citations,
    build_domain_channel_index,
    build_published_index,
    resolve_channel_domain,
    resolve_published,
    url_key,
)
from app.services.monitoring_extraction import AnswerPayload, CitationInput, apply_answer_payload
from app.services.stats import sources


def _make_project(db, code: str) -> Project:
    project = Project(code=code, name="广州基地", status=ProjectStatus.ACTIVE, timezone="Asia/Shanghai")
    db.add(project)
    db.flush()
    return project


def _add_channel(db, project: Project, code: str, *, primary_domain: str | None = None) -> Channel:
    channel = Channel(
        project_id=project.id,
        code=code,
        name=code,
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
        primary_domain=primary_domain,
    )
    db.add(channel)
    db.flush()
    return channel


def _add_receipt(db, project: Project, channel: Channel, published_url: str, *, minutes: int = 0) -> PublishTask:
    """造一条"已发布"闭环：内容版本 → 发布任务 → 回执（真实 URL）。"""
    item = ContentItem(project_id=project.id, title=f"稿-{uuid.uuid4().hex[:6]}", kind=ContentKind.MASTER)
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body="正文",
        content_hash=uuid.uuid4().hex,
        status=ContentStatus.DRAFT,
    )
    db.add(version)
    db.flush()
    account = PublishAccount(
        project_id=project.id, channel_id=channel.id, account_name=f"账号-{uuid.uuid4().hex[:6]}"
    )
    db.add(account)
    db.flush()
    task = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"t-{uuid.uuid4().hex[:8]}",
        idempotency_key=f"i-{uuid.uuid4().hex[:8]}",
    )
    db.add(task)
    db.flush()
    db.add(
        PublishReceipt(
            project_id=project.id,
            task_id=task.id,
            published_url=published_url,
            received_at=datetime.now(timezone.utc) + timedelta(minutes=minutes),
        )
    )
    db.flush()
    return task


def _make_sample(db, project: Project) -> MonitoringSample:
    question = Question(
        project_id=project.id,
        code=f"Q-{uuid.uuid4().hex[:6]}",
        title="归因用例题",
        question_type=QuestionType.GENERAL,
        status=QuestionStatus.ACTIVE,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text=question.title)
    engine = AiEngine(code=f"e-{uuid.uuid4().hex[:6]}", name="测试引擎", vendor="test", supports_search=True)
    db.add_all([version, engine])
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        name="测试入口",
        entry_type=EngineEntryType.WEB_USER,
        entry_url="https://example.com",
        is_active=True,
    )
    db.add(entry)
    db.flush()
    seq = int(
        db.scalar(select(func.max(MonitoringRound.seq)).where(MonitoringRound.project_id == project.id)) or 0
    ) + 1
    round_row = MonitoringRound(project_id=project.id, seq=seq, name="归因轮次", status=RoundStatus.RUNNING)
    db.add(round_row)
    db.flush()
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.RUNNING,
    )
    db.add(task)
    db.flush()
    sample = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        status=SampleStatus.HIT,
        sampled_at=datetime.now(timezone.utc),
    )
    db.add(sample)
    db.flush()
    return sample


def test_url_key_ignores_scheme_www_slash_and_tracking_but_keeps_article_id():
    assert url_key("https://www.36kr.com/p/geo-live-smoke/") == url_key("http://36kr.com/p/geo-live-smoke")
    assert url_key("https://36kr.com/p/1?p=2&utm_source=x&gclid=y") == "36kr.com/p/1?p=2"
    # 跟踪参数不影响同一页面判定
    assert url_key("https://36kr.com/p/1?utm_source=a") == url_key("https://36kr.com/p/1")
    assert url_key("") == ""


def test_published_index_uses_latest_receipt(db):
    project = _make_project(db, f"attr-idx-{uuid.uuid4().hex[:6]}")
    channel = _add_channel(db, project, "36kr")
    _add_receipt(db, project, channel, "https://36kr.com/p/a")
    index = build_published_index(db, project.id)
    target = resolve_published(index, "http://www.36kr.com/p/a/?utm_source=ai")
    assert target is not None
    assert target.channel_id == channel.id


def test_citation_channel_only_when_url_matches_receipt(db):
    """同域名但不同页面不能算渠道被引——这正是域名匹配的老问题。"""
    project = _make_project(db, f"attr-write-{uuid.uuid4().hex[:6]}")
    channel = _add_channel(db, project, "36kr")
    _add_receipt(db, project, channel, "https://36kr.com/p/geo-live-smoke")
    sample = _make_sample(db, project)

    apply_answer_payload(
        db,
        sample,
        AnswerPayload(
            text="参考报道",
            citations=[
                CitationInput(url="https://36kr.com/p/geo-live-smoke", usage=CitationUsage.CITED),
                CitationInput(url="https://36kr.com/p/someone-else", usage=CitationUsage.CITED),
            ],
        ),
    )
    rows = db.scalars(select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id)).all()
    by_url = {row.normalized_url: row.channel_id for row in rows}
    assert by_url["https://36kr.com/p/geo-live-smoke"] == channel.id
    assert by_url["https://36kr.com/p/someone-else"] is None


def test_backfill_attaches_historical_citations_by_url(db):
    project = _make_project(db, f"attr-bf-{uuid.uuid4().hex[:6]}")
    channel = _add_channel(db, project, "zhihu")
    sample = _make_sample(db, project)
    apply_answer_payload(
        db,
        sample,
        AnswerPayload(text="引用", citations=[CitationInput(url="https://zhuanlan.zhihu.com/p/1")]),
    )
    # 模拟历史数据：采集时还没有回执
    db.execute(
        MonitoringCitation.__table__.update()
        .where(MonitoringCitation.sample_id == sample.id)
        .values(channel_id=None)
    )
    db.flush()

    no_receipt = backfill_project_citations(db, project.id)
    assert no_receipt["matched"] == 0

    _add_receipt(db, project, channel, "https://zhuanlan.zhihu.com/p/1")
    result = backfill_project_citations(db, project.id)
    assert result["matched"] == 1
    citation = db.scalar(select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id))
    assert citation.channel_id == channel.id

    # 幂等：已归类的不再进候选
    again = backfill_project_citations(db, project.id)
    assert again["candidates"] == 0


def test_backfill_does_not_commit_and_flushes_when_caller_commits(db, monkeypatch):
    """回刷只 flush，不替调用方 commit；脚本按项目提交。"""
    project = _make_project(db, f"attr-nc-{uuid.uuid4().hex[:6]}")
    channel = _add_channel(db, project, "zhihu")
    sample = _make_sample(db, project)
    apply_answer_payload(
        db,
        sample,
        AnswerPayload(text="引用", citations=[CitationInput(url="https://zhuanlan.zhihu.com/p/2")]),
    )
    db.execute(
        MonitoringCitation.__table__.update()
        .where(MonitoringCitation.sample_id == sample.id)
        .values(channel_id=None)
    )
    db.flush()
    _add_receipt(db, project, channel, "https://zhuanlan.zhihu.com/p/2")

    commits: list[str] = []
    monkeypatch.setattr(db, "commit", lambda: commits.append("commit"))

    result = backfill_project_citations(db, project.id)
    assert result["matched"] == 1
    assert commits == []

    citation = db.scalar(select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id))
    assert citation.channel_id == channel.id


def test_backfill_batches_with_small_batch_size(db):
    """keyset 分批：batch_size 小于候选数时逐批命中，不重复计数、不重复写。"""
    project = _make_project(db, f"attr-batch-{uuid.uuid4().hex[:6]}")
    channel = _add_channel(db, project, "zhihu")
    sample = _make_sample(db, project)
    urls = [f"https://zhuanlan.zhihu.com/p/batch-{index}" for index in range(5)]
    apply_answer_payload(
        db,
        sample,
        AnswerPayload(text="引用", citations=[CitationInput(url=url) for url in urls]),
    )
    # 采集时还没有回执，先清空渠道归属模拟历史数据
    db.execute(
        MonitoringCitation.__table__.update()
        .where(MonitoringCitation.sample_id == sample.id)
        .values(channel_id=None)
    )
    db.flush()
    for url in urls:
        _add_receipt(db, project, channel, url)

    result = backfill_project_citations(db, project.id, batch_size=2)
    assert result["candidates"] == 5
    assert result["matched"] == 5
    assert result["unmatched"] == 0

    rows = db.scalars(select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id)).all()
    assert all(row.channel_id == channel.id for row in rows)

    # 再跑一次：已归类的行不再进候选
    again = backfill_project_citations(db, project.id, batch_size=2)
    assert again["candidates"] == 0


def test_resolve_channel_domain_matches_exact_and_suffix_only():
    """域名归渠道：精确或后缀上溯（子域归母域渠道）；不可反向用母域盖子域渠道。"""
    index = {
        "zhihu.com": uuid.uuid4(),
        "baike.baidu.com": uuid.uuid4(),
    }
    assert resolve_channel_domain(index, "zhuanlan.zhihu.com") == index["zhihu.com"]
    assert resolve_channel_domain(index, "zhihu.com") == index["zhihu.com"]
    assert resolve_channel_domain(index, "baike.baidu.com") == index["baike.baidu.com"]
    # baidu.com 不是 baike.baidu.com 的上级域名，不能误配
    assert resolve_channel_domain(index, "baidu.com") is None
    assert resolve_channel_domain(index, "github.com") is None
    assert resolve_channel_domain(index, None) is None


def test_observed_promotes_candidate_channel_by_citation_domain(db):
    """引用域名命中渠道台账 → 候选渠道自动推进到 observed。"""
    project = _make_project(db, f"attr-obs-{uuid.uuid4().hex[:6]}")
    channel = _add_channel(db, project, "zhihu", primary_domain="zhihu.com")
    sample = _make_sample(db, project)

    apply_answer_payload(
        db,
        sample,
        AnswerPayload(
            text="参考",
            citations=[CitationInput(url="https://zhuanlan.zhihu.com/p/1")],
        ),
    )
    db.flush()
    assert db.get(Channel, channel.id).status == ChannelStatus.OBSERVED


def test_observed_does_not_downgrade_published_channel(db):
    """已发布渠道被引用时保持 published：发布产出事实不被观测覆盖。"""
    project = _make_project(db, f"attr-obsp-{uuid.uuid4().hex[:6]}")
    channel = _add_channel(db, project, "36kr", primary_domain="36kr.com")
    channel.status = ChannelStatus.PUBLISHED
    db.flush()
    sample = _make_sample(db, project)

    apply_answer_payload(
        db,
        sample,
        AnswerPayload(text="参考", citations=[CitationInput(url="https://36kr.com/p/x")]),
    )
    db.flush()
    assert db.get(Channel, channel.id).status == ChannelStatus.PUBLISHED


def test_observed_ignores_unrelated_domain(db):
    project = _make_project(db, f"attr-obsn-{uuid.uuid4().hex[:6]}")
    channel = _add_channel(db, project, "zhihu", primary_domain="zhihu.com")
    sample = _make_sample(db, project)

    apply_answer_payload(
        db,
        sample,
        AnswerPayload(text="参考", citations=[CitationInput(url="https://github.com/a/b")]),
    )
    db.flush()
    assert db.get(Channel, channel.id).status == ChannelStatus.CANDIDATE


def test_domain_channel_index_includes_aliases(db):
    project = _make_project(db, f"attr-obsal-{uuid.uuid4().hex[:6]}")
    channel = _add_channel(db, project, "zhihu", primary_domain="zhihu.com")
    db.add(
        ChannelAlias(
            project_id=project.id,
            channel_id=channel.id,
            domain="zhihu.com.cn",
        )
    )
    db.flush()
    index = build_domain_channel_index(db, project.id)
    assert resolve_channel_domain(index, "zhihu.com.cn") == channel.id
    assert resolve_channel_domain(index, "www.zhihu.com") == channel.id


def test_sources_lists_domains_and_separates_channel_citations(db):
    project = _make_project(db, f"attr-src-{uuid.uuid4().hex[:6]}")
    channel = _add_channel(db, project, "36kr")
    _add_receipt(db, project, channel, "https://36kr.com/p/mine")
    sample = _make_sample(db, project)
    apply_answer_payload(
        db,
        sample,
        AnswerPayload(
            text="参考",
            citations=[
                CitationInput(url="https://36kr.com/p/mine", usage=CitationUsage.CITED),
                CitationInput(url="https://36kr.com/p/other", usage=CitationUsage.CITED),
                CitationInput(url="https://zhuanlan.zhihu.com/p/9", usage=CitationUsage.CITED),
            ],
        ),
    )
    rows = sources(db, project.id, limit=10)
    by_domain = {row["domain"]: row for row in rows}
    assert by_domain["36kr.com"]["citations"] == 2
    # 只有命中回执的那一条算渠道效果
    assert by_domain["36kr.com"]["channel_citations"] == 1
    assert by_domain["zhuanlan.zhihu.com"]["channel_citations"] == 0

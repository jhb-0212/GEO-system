"""自动采集链与内部 GEO 指标回归测试。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.services.monitoring_collection as collection_module
import app.services.monitoring_extraction as extraction_module
from app.core.config import settings

from app.models import (
    AiEngine,
    AiEngineEntry,
    Competitor,
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    OutboxEvent,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    CitationUsage,
    EngineEntryType,
    FailureCode,
    OutboxStatus,
    ProjectStatus,
    QuestionStatus,
    QuestionType,
    ReviewResult,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.monitoring_collection import (
    EngineRateLimiter,
    RateLimitedFailure,
    TransientCollectionFailure,
    execute_task,
    mark_task_failed,
    plan_round_tasks,
    run_pending_tasks,
    schedule_active_rounds,
)
from app.services.monitoring_extraction import (
    AnswerPayload,
    CitationInput,
    CompetitorMentionInput,
    detect_brand_mention,
    normalize_url,
    parse_raw_response,
)
from app.services.outbox_dispatch import dispatch_pending_events
from app.services.stats import geo_overview
from app.services.trace_chain import trace_detail


class FakeAdapter:
    def __init__(self, payload: AnswerPayload) -> None:
        self.payload = payload
        self.calls = 0

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        self.calls += 1
        return self.payload


def _make_round(db, project, *, seq=1, baseline=True, status=RoundStatus.RUNNING) -> MonitoringRound:
    row = MonitoringRound(
        project_id=project.id,
        seq=seq,
        name=f"轮次-{seq}",
        is_baseline=baseline,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def _make_question(db, project, *, code=None) -> tuple[Question, QuestionVersion]:
    suffix = uuid.uuid4().hex[:6]
    question = Question(
        project_id=project.id,
        code=code or f"Q-{suffix}",
        title="测试问题",
        question_type=QuestionType.BRAND,
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
        text="测试问题正文",
    )
    db.add(version)
    db.flush()
    return question, version


def _make_engine(db, *, code=None) -> tuple[AiEngine, AiEngineEntry]:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(
        code=code or f"eng-{suffix}",
        name=f"引擎-{suffix}",
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
        name=f"入口-{suffix}",
        supports_search=True,
        is_active=True,
    )
    db.add(entry)
    db.flush()
    return engine, entry


def test_normalize_and_detect_brand():
    raw, domain = normalize_url("https://www.Example.com/a?utm=x")
    assert raw.startswith("https://")
    assert domain == "example.com"
    assert detect_brand_mention("推荐广州基地的课程", ["广州基地"]) is True
    assert detect_brand_mention("无关内容", ["广州基地"]) is False


def test_parse_raw_response_supports_common_shape():
    payload = parse_raw_response(
        {
            "answer": "推荐广州基地",
            "citations": [
                {"url": "https://example.com/a", "usage": "used"},
                "https://example.com/b",
            ],
            "competitors": ["竞品甲", {"name": "竞品乙", "position": 2}],
            "engine_model": "doubao",
            "country_code": "CN",
        }
    )
    assert payload.text == "推荐广州基地"
    assert len(payload.citations) == 2
    assert payload.citations[0].usage == CitationUsage.USED
    assert payload.citations[1].usage == CitationUsage.CITED
    assert [m.name for m in payload.competitor_mentions] == ["竞品甲", "竞品乙"]
    assert payload.engine_model == "doubao"


def test_apply_answer_payload_persists_citation_and_mentions(db, project_factory):
    project = project_factory(f"extract-{uuid.uuid4().hex[:6]}")
    _question, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
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
        status=SampleStatus.RUNNING,
        sampling_mode=SamplingMode.SEARCH_ON,
    )
    db.add(sample)
    db.flush()

    payload = AnswerPayload(
        text="广州基地被推荐，竞品甲也被提到",
        citations=[
            CitationInput(url="https://www.Example.com/a?utm=x", usage=CitationUsage.USED),
            CitationInput(url="https://competitor.example/b", usage=CitationUsage.CITED, competitor_name="竞品甲"),
        ],
        competitor_mentions=[
            CompetitorMentionInput(name="竞品甲", position=2, evidence_text="竞品甲也被提到")
        ],
    )
    from app.services.monitoring_extraction import apply_answer_payload

    result = apply_answer_payload(db, sample, payload, brand_terms=["广州基地"])
    assert result == {
        "brand_mentioned": True,
        "brand_identified": False,
        "citation_count": 2,
        "competitor_mention_count": 1,
    }
    assert sample.brand_mentioned is True
    assert len(db.scalars(select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id)).all()) == 2
    assert {c.citation_usage for c in db.scalars(select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id)).all()} == {
        CitationUsage.USED,
        CitationUsage.CITED,
    }
    competitor = db.scalar(select(Competitor).where(Competitor.name == "竞品甲"))
    assert competitor is not None
    mention = db.scalar(select(MonitoringCompetitorMention).where(MonitoringCompetitorMention.sample_id == sample.id))
    assert mention is not None and mention.competitor_id == competitor.id

    # 重复回填不应重复插引用/提及
    apply_answer_payload(db, sample, payload, brand_terms=["广州基地"])
    assert len(db.scalars(select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id)).all()) == 2
    assert len(db.scalars(select(MonitoringCompetitorMention).where(MonitoringCompetitorMention.sample_id == sample.id)).all()) == 1


@pytest.fixture()
def geo_fixture(db, project_factory):
    project = project_factory(f"geo-{uuid.uuid4().hex[:6]}", name="广州基地")
    question, version = _make_question(db, project)
    engine, entry = _make_engine(db)
    round_row = _make_round(db, project, seq=1, baseline=True, status=RoundStatus.RUNNING)
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

    now = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
    hit = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        status=SampleStatus.HIT,
        sampled_at=now - timedelta(hours=2),
        sampling_mode=SamplingMode.SEARCH_ON,
        brand_mentioned=True,
        review_result=ReviewResult.HIT,
    )
    miss = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=2,
        status=SampleStatus.MISS,
        sampled_at=now - timedelta(hours=3),
        sampling_mode=SamplingMode.SEARCH_ON,
        brand_mentioned=False,
        review_result=ReviewResult.MISS,
    )
    failed = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=3,
        status=SampleStatus.FAILED,
        sampled_at=now - timedelta(hours=4),
        sampling_mode=SamplingMode.SEARCH_ON,
        failure_code=FailureCode.ACCESS_BLOCKED,
    )
    db.add_all([hit, miss, failed])
    db.flush()

    competitor = Competitor(project_id=project.id, name="竞品甲", domain="competitor.example")
    db.add(competitor)
    db.flush()
    citation_brand = MonitoringCitation(
        project_id=project.id,
        sample_id=hit.id,
        raw_url="https://example.com/brand",
        normalized_url="https://example.com/brand",
        domain="example.com",
        is_brand_related=True,
        citation_usage=CitationUsage.USED,
    )
    citation_competitor = MonitoringCitation(
        project_id=project.id,
        sample_id=hit.id,
        raw_url="https://competitor.example/a",
        normalized_url="https://competitor.example/a",
        domain="competitor.example",
        is_brand_related=False,
        citation_usage=CitationUsage.CITED,
        competitor_id=competitor.id,
    )
    db.add_all([citation_brand, citation_competitor])
    db.add(
        MonitoringCompetitorMention(
            project_id=project.id,
            sample_id=hit.id,
            competitor_id=competitor.id,
            position=1,
            evidence_text="竞品甲",
        )
    )
    db.flush()
    return {"project": project, "now": now, "question": question, "engine": engine, "entry": entry, "round": round_row, "task": task}


def test_geo_overview_has_business_metrics(db, geo_fixture):
    report = geo_overview(db, geo_fixture["project"].id, now=geo_fixture["now"])
    assert report["valid_answers"] == 2
    assert report["mention_rate"] == 0.5
    assert report["citation_share"] == 0.5
    assert report["sov"] == 0.5
    assert report["prompt_coverage"] == 1.0
    assert report["freshness_hours"] == 2.0
    assert report["fresh_24h_rate"] == 1.0
    assert report["failure_rate"] == round(1 / 3, 4)
    assert report["counts"]["used_citations"] == 1
    assert report["counts"]["cited_citations"] == 1
    assert report["by_competitor"] == [{"competitor": "竞品甲", "mentioned_samples": 1}]
    assert "有效回答" in report["statement"]


def test_geo_overview_zero_valid_answers_is_explicit(db, project_factory):
    project = project_factory(f"zero-{uuid.uuid4().hex[:6]}")
    report = geo_overview(db, project.id)
    assert report["valid_answers"] == 0
    assert report["mention_rate"] is None
    assert report["statement"].startswith("有效回答 0")


def test_plan_round_tasks_is_idempotent_and_dynamic_engine_count(db, project_factory):
    project = project_factory(f"plan-{uuid.uuid4().hex[:6]}")
    _q, version = _make_question(db, project)
    # 系统级引擎是全局目录；先把现有 active 引擎停用，避免测试受种子数据影响
    for row in db.scalars(select(AiEngine).where(AiEngine.is_active.is_(True))).all():
        row.is_active = False
    db.flush()
    _e1, entry1 = _make_engine(db)
    _e2, entry2 = _make_engine(db)
    round_row = _make_round(db, project)
    # 两个引擎，不是硬编码 4
    first = plan_round_tasks(db, project_id=project.id, round_id=round_row.id)
    assert first["created_task_ids"] and len(first["created_task_ids"]) == 2
    assert first["engine_count"] == 2
    second = plan_round_tasks(db, project_id=project.id, round_id=round_row.id)
    assert second["created_task_ids"] == []
    assert second["existing_task_count"] == 2


def test_schedule_emits_outbox_for_new_tasks(db, project_factory):
    project = project_factory(f"sched-{uuid.uuid4().hex[:6]}")
    _q, _version = _make_question(db, project)
    for row in db.scalars(select(AiEngine).where(AiEngine.is_active.is_(True))).all():
        row.is_active = False
    db.flush()
    _engine, _entry = _make_engine(db)
    round_row = _make_round(db, project, status=RoundStatus.PLANNING)
    result = schedule_active_rounds(db, project_id=project.id)
    assert result["created_task_count"] == 1
    events = db.scalars(
        select(OutboxEvent).where(
            OutboxEvent.project_id == project.id,
            OutboxEvent.topic == "monitoring.task.execute",
        )
    ).all()
    assert len(events) == 1
    assert events[0].payload["task_id"]


def test_execute_task_with_adapter_and_default_failure(db, project_factory):
    project = project_factory(f"exec-{uuid.uuid4().hex[:6]}", name="广州基地")
    _q, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()

    adapter = FakeAdapter(
        AnswerPayload(
            text="广州基地推荐",
            citations=[CitationInput(url="https://example.com/a", usage=CitationUsage.CITED)],
            competitor_mentions=[CompetitorMentionInput(name="竞品甲")],
            engine_model="doubao-pro",
        )
    )
    result = execute_task(
        db,
        project_id=project.id,
        task_id=task.id,
        adapter=adapter,
    )
    assert result["status"] == "hit"
    assert adapter.calls == 1
    sample = db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task.id))
    assert sample.engine_model == "doubao-pro"
    assert sample.brand_mentioned is True
    assert db.scalar(select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id)) is not None
    assert db.scalar(select(MonitoringCompetitorMention).where(MonitoringCompetitorMention.sample_id == sample.id)) is not None

    # 未配置适配器：明确失败，不伪造 hit/miss
    task2 = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=2,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task2)
    db.flush()
    result2 = execute_task(db, project_id=project.id, task_id=task2.id)
    assert result2["status"] == "failed"
    assert result2["failure_code"] == FailureCode.ACCESS_BLOCKED.value
    assert db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task2.id)).status == SampleStatus.FAILED


def test_rate_limit_blocks_before_sample(db, project_factory):
    project = project_factory(f"rate-{uuid.uuid4().hex[:6]}")
    _q, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()

    class DenyLimiter(EngineRateLimiter):
        def allow(self, engine_code: str, *, now=None) -> bool:
            return False

    with pytest.raises(RateLimitedFailure):
        execute_task(db, project_id=project.id, task_id=task.id, rate_limiter=DenyLimiter())
    assert db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task.id)) is None


def test_websearch_round_cap_blocks_extra_tasks(db, project_factory):
    """同一轮次网页端最多跑 N 条，超出不建样本、不发请求。"""
    project = project_factory(f"cap-{uuid.uuid4().hex[:6]}")
    _q, version = _make_question(db, project)
    _engine, entry = _make_engine(db, code="deepseek_websearch")
    round_row = _make_round(db, project)
    cap = int(settings.monitoring_websearch_round_cap)
    for index in range(cap):
        db.add(
            MonitoringTask(
                project_id=project.id,
                round_id=round_row.id,
                question_version_id=version.id,
                engine_entry_id=entry.id,
                sampling_no=index + 1,
                sampling_mode=SamplingMode.SEARCH_ON,
                status=TaskStatus.DONE,
            )
        )
    extra = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=cap + 1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(extra)
    db.flush()

    result = execute_task(db, project_id=project.id, task_id=extra.id)
    assert result["status"] == "failed"
    assert result["failure_code"] == "other"
    assert "上限" in result["note"]
    quota_sample = db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == extra.id))
    assert quota_sample is not None
    assert quota_sample.status == SampleStatus.FAILED
    assert quota_sample.failure_code == FailureCode.OTHER
    assert "上限" in (quota_sample.failure_note or "")


def test_websearch_round_cap_ignores_failed_tasks(db, project_factory):
    """失败任务不占单轮配额：已有失败任务时仍允许继续采。"""
    project = project_factory(f"capf-{uuid.uuid4().hex[:6]}")
    _q, version = _make_question(db, project)
    _engine, entry = _make_engine(db, code="deepseek_websearch")
    round_row = _make_round(db, project)
    cap = int(settings.monitoring_websearch_round_cap)
    for index in range(cap):
        db.add(
            MonitoringTask(
                project_id=project.id,
                round_id=round_row.id,
                question_version_id=version.id,
                engine_entry_id=entry.id,
                sampling_no=index + 1,
                sampling_mode=SamplingMode.SEARCH_ON,
                status=TaskStatus.FAILED,
            )
        )
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=cap + 1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()

    result = execute_task(
        db,
        project_id=project.id,
        task_id=task.id,
        adapter=FakeAdapter(AnswerPayload(text="答案")),
    )
    assert result["status"] != "failed", result


def test_outbox_dispatch_marks_dispatched_and_keeps_pending_on_failure(db, project_factory):
    project = project_factory(f"outbox-{uuid.uuid4().hex[:6]}")
    from app.services.outbox import emit_event

    event_ok = emit_event(db, project_id=project.id, topic="monitoring.task.execute", payload={"project_id": str(project.id), "task_id": str(uuid.uuid4())})
    event_fail = emit_event(db, project_id=project.id, topic="monitoring.task.execute", payload={"project_id": str(project.id), "task_id": str(uuid.uuid4())})
    db.flush()

    def send(event: OutboxEvent) -> None:
        if event.id == event_fail.id:
            raise RuntimeError("broker timeout")

    result = dispatch_pending_events(db, send)
    assert result["dispatched_count"] == 1
    assert result["failed_count"] == 1
    assert event_ok.status == OutboxStatus.DISPATCHED
    assert event_fail.status == OutboxStatus.PENDING


def test_plan_round_tasks_reports_skip_reasons(db, project_factory):
    project = project_factory(f"skip-{uuid.uuid4().hex[:6]}")
    round_row = _make_round(db, project)
    result = plan_round_tasks(db, project_id=project.id, round_id=round_row.id)
    assert result["created_task_ids"] == []
    assert result["skipped_reason"] == "no_active_question"

    _q, _version = _make_question(db, project)
    for row in db.scalars(select(AiEngine).where(AiEngine.is_active.is_(True))).all():
        row.is_active = False
    db.flush()
    result2 = plan_round_tasks(db, project_id=project.id, round_id=round_row.id)
    assert result2["skipped_reason"] == "engine_entries_insufficient"


def test_engine_rate_limiter_counts_and_fails_open():
    class FakeRedis:
        def __init__(self, fail=False) -> None:
            self.count = 0
            self.expires = 0
            self.fail = fail

        def incr(self, key):
            if self.fail:
                raise __import__("redis").RedisError("down")
            self.count += 1
            return self.count

        def expire(self, key, seconds):
            self.expires += 1
            return True

    limiter = EngineRateLimiter(client=FakeRedis(), limit_per_minute=2)
    assert limiter.allow("eng", now=datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)) is True
    assert limiter.allow("eng", now=datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)) is True
    assert limiter.allow("eng", now=datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)) is False
    assert EngineRateLimiter(client=FakeRedis(fail=True), limit_per_minute=2).allow("eng") is True


def test_websearch_engine_uses_stricter_rate_limit():
    """网页端采集默认 1 次/分钟，普通 API 引擎仍按全局上限。"""

    class FakeRedis:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}
            self.keys: dict[str, str] = {}

        def incr(self, key):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        def expire(self, key, seconds):
            return True

        def exists(self, key):
            return 1 if key in self.keys else 0

        def set(self, key, value, ex=None):
            self.keys[key] = value
            return True

    now = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
    fake = FakeRedis()
    limiter = EngineRateLimiter(client=fake)
    assert limiter.allow("deepseek_websearch", now=now) is True
    assert limiter.allow("deepseek_websearch", now=now) is False
    # 同一分钟内普通引擎不受网页端那 1 次额度影响
    for _ in range(3):
        assert limiter.allow("openai_compatible", now=now) is True

    # 被限流后整引擎冷却：冷却期内一律不放行
    limiter.trip_cooldown("deepseek_websearch")
    assert limiter.allow("deepseek_websearch", now=now) is False
    # 普通引擎不参与网页端冷却
    assert limiter.allow("openai_compatible", now=now) is True


def test_websearch_daily_cap_blocks_beyond_budget():
    """网页端每日调用超过上限后直接拒绝，避免长时间连续抓取。"""

    class FakeRedis:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}
            self.keys: dict[str, str] = {}

        def incr(self, key):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        def expire(self, key, seconds):
            return True

        def exists(self, key):
            return 1 if key in self.keys else 0

        def set(self, key, value, ex=None):
            self.keys[key] = value
            return True

    fake = FakeRedis()
    limiter = EngineRateLimiter(client=fake)
    cap = int(settings.monitoring_websearch_daily_cap)
    now = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
    # 分钟窗口会被打满，这里只验证日额度：每"分钟"调一次，绕开 2 次/分钟的限制
    allowed = 0
    for minute in range(0, cap + 5):
        moment = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc).replace(minute=0) + timedelta(
            minutes=minute
        )
        if limiter.allow("deepseek_websearch", now=moment):
            allowed += 1
    assert allowed == cap


def test_websearch_minute_limit_does_not_burn_daily_quota():
    """同一分钟内被分钟限流挡掉的调度，不能扣掉当日额度。"""

    class FakeRedis:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}
            self.keys: dict[str, str] = {}

        def incr(self, key):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        def expire(self, key, seconds):
            return True

        def exists(self, key):
            return 1 if key in self.keys else 0

        def set(self, key, value, ex=None):
            self.keys[key] = value
            return True

    fake = FakeRedis()
    limiter = EngineRateLimiter(client=fake)
    now = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
    # 一分钟内连发 5 次：只有第 1 次真正放行，其余是分钟窗口拒绝
    assert [limiter.allow("deepseek_websearch", now=now) for _ in range(5)] == [
        True,
        False,
        False,
        False,
        False,
    ]
    daily_key = "geo:monitoring:daily:deepseek_websearch:20261112"
    assert fake.counts[daily_key] == 1


def test_rate_limited_task_lands_failed_after_worker_commit(db, project_factory):
    """worker 限流分支先 commit 再落失败：pending 任务不能卡在 pending。"""
    project = project_factory(f"ratelimit-{uuid.uuid4().hex[:6]}")
    _q, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()

    class DenyLimiter(EngineRateLimiter):
        def allow(self, engine_code: str, *, now=None) -> bool:
            return False

    with pytest.raises(RateLimitedFailure):
        execute_task(db, project_id=project.id, task_id=task.id, rate_limiter=DenyLimiter())

    # 模拟 worker.py 的 RateLimitedFailure 分支：commit 保留 running，再落失败
    db.commit()
    mark_task_failed(
        db,
        project_id=project.id,
        task_id=task.id,
        failure_code=FailureCode.RATE_LIMITED,
        note="每分钟调用上限",
    )
    db.flush()

    assert db.scalar(select(MonitoringTask).where(MonitoringTask.id == task.id)).status == TaskStatus.FAILED


def test_mark_task_failed_tolerates_still_pending_task(db, project_factory):
    """兜底：即使调用方回滚掉了 running，mark_task_failed 也不能被状态机拒绝。"""
    project = project_factory(f"pendingfail-{uuid.uuid4().hex[:6]}")
    _q, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()

    mark_task_failed(
        db,
        project_id=project.id,
        task_id=task.id,
        failure_code=FailureCode.RATE_LIMITED,
        note="回滚后直接落失败",
    )
    db.flush()

    assert db.scalar(select(MonitoringTask).where(MonitoringTask.id == task.id)).status == TaskStatus.FAILED


def test_transient_failure_keeps_sample_then_mark_task_failed(db, project_factory):
    project = project_factory(f"transient-{uuid.uuid4().hex[:6]}")
    _q, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()

    class TimeoutAdapter:
        def collect(self, _task):
            raise TransientCollectionFailure("upstream timeout")

    with pytest.raises(TransientCollectionFailure):
        execute_task(db, project_id=project.id, task_id=task.id, adapter=TimeoutAdapter())
    sample = db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task.id))
    assert sample.status == SampleStatus.FAILED
    assert sample.failure_code == FailureCode.TIMEOUT
    assert task.status == TaskStatus.RUNNING

    mark_task_failed(
        db,
        project_id=project.id,
        task_id=task.id,
        failure_code=FailureCode.TIMEOUT,
        note="retry exhausted",
    )
    assert task.status == TaskStatus.FAILED


def test_execute_terminal_task_is_skipped_and_run_pending_counts(db, project_factory):
    project = project_factory(f"pending-{uuid.uuid4().hex[:6]}")
    _q, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
    done = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.DONE,
    )
    pending = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=2,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add_all([done, pending])
    db.flush()
    skipped = execute_task(db, project_id=project.id, task_id=done.id)
    assert skipped["skipped"] == "task already terminal"
    counts = run_pending_tasks(db, project_id=project.id, round_id=round_row.id)
    assert counts["task_count"] == 1
    assert counts["executed_count"] == 1
    assert counts["failed_count"] == 1


def test_run_pending_marks_retryable_failure_terminal(db, project_factory):
    """批量补跑不重试：可重试失败也必须落 failed 终态，不能停在 running。"""
    project = project_factory(f"pending-retry-{uuid.uuid4().hex[:6]}")
    _q, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()

    class TimeoutAdapter:
        def collect(self, _task):
            raise TransientCollectionFailure("upstream timeout")

    counts = run_pending_tasks(db, project_id=project.id, adapter=TimeoutAdapter())
    assert counts["failed_count"] == 1

    refreshed = db.scalar(select(MonitoringTask).where(MonitoringTask.id == task.id))
    assert refreshed.status == TaskStatus.FAILED


def test_run_pending_builds_published_index_once(db, project_factory, monkeypatch):
    """整批补跑只建一次发布回执索引，不在每个样本各查一遍。"""
    project = project_factory(f"pending-index-{uuid.uuid4().hex[:6]}")
    _q, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
    tasks = [
        MonitoringTask(
            project_id=project.id,
            round_id=round_row.id,
            question_version_id=version.id,
            engine_entry_id=entry.id,
            sampling_no=no,
            sampling_mode=SamplingMode.SEARCH_ON,
            status=TaskStatus.PENDING,
        )
        for no in (1, 2)
    ]
    db.add_all(tasks)
    db.flush()

    calls = {"count": 0}
    real_build = extraction_module.build_published_index

    def counting_build(db_, project_id):
        calls["count"] += 1
        return real_build(db_, project_id)

    monkeypatch.setattr(extraction_module, "build_published_index", counting_build)
    monkeypatch.setattr(collection_module, "build_published_index", counting_build)

    counts = run_pending_tasks(
        db,
        project_id=project.id,
        adapter=FakeAdapter(AnswerPayload(text="答案")),
    )
    assert counts["executed_count"] == 2
    assert calls["count"] == 1


def test_trace_detail_links_round_task_sample_and_citation(db, project_factory):
    project = project_factory(f"trace-{uuid.uuid4().hex[:6]}")
    _question, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
    trace_id = uuid.uuid4().hex
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.DONE,
        trace_id=trace_id,
    )
    db.add(task)
    db.flush()
    sample = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        trace_id=trace_id,
        status=SampleStatus.HIT,
        sampling_mode=SamplingMode.SEARCH_ON,
        brand_mentioned=True,
    )
    db.add(sample)
    db.flush()
    citation = MonitoringCitation(
        project_id=project.id,
        sample_id=sample.id,
        trace_id=trace_id,
        raw_url="https://example.com/a",
        normalized_url="https://example.com/a",
        domain="example.com",
        is_brand_related=True,
        citation_usage=CitationUsage.CITED,
    )
    db.add(citation)
    db.flush()

    detail = trace_detail(db, project_id=project.id, trace_id=trace_id)
    assert detail["found"] is True
    assert detail["rounds"][0]["id"] == str(round_row.id)
    assert detail["tasks"][0]["id"] == str(task.id)
    assert detail["samples"][0]["brand_mentioned"] is True
    assert detail["citations"][0]["domain"] == "example.com"
    assert detail["counts"]["tasks"] == 1
    assert detail["counts"]["citations"] == 1
    assert detail["publish_tasks"] == []

    missing = trace_detail(db, project_id=project.id, trace_id="missing-trace")
    assert missing["found"] is False
    assert missing["counts"]["tasks"] == 0
def test_geo_overview_brand_sentiment_and_position(db, project_factory):
    project = project_factory(f"sent-{uuid.uuid4().hex[:6]}", name="广州基地")
    _question, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    round_row = _make_round(db, project)
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
        brand_mentioned=True,
        raw_answer="竞品甲口碑不错。广州基地被推荐，课程适合就业实训。",
    )
    db.add(sample)
    db.flush()

    result = geo_overview(db, project.id)
    assert result["sentiment"]["positive"] == 1
    assert result["sentiment"]["not_mentioned"] == 0
    assert result["sentiment"]["positive_rate"] == 1.0
    assert result["brand_position"]["sample_count"] == 1
    assert result["brand_position"]["average_rank"] == 1.0
    assert result["brand_position"]["top1_rate"] == 1.0
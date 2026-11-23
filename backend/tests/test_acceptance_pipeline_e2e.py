"""端到端验收：抽样 → 双人标注 → 跨轮累计共识 → 契约正向率。

用测试数据证明这条链路能走通，不依赖真实库：
1. 只有单人标注时，契约仍不出正向率；
2. 两人同档达到 50 条共识后，契约给出正向率并把它从 missing 里移除。
"""

import uuid
from datetime import UTC, datetime

from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
    SentimentLabel,
)
from app.models.enums import (
    CitationPageType,
    CitationReviewStatus,
    EngineEntryType,
    QuestionType,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    SentimentPolarity,
    SourceCategory,
    TaskStatus,
)
from app.services.acceptance_contract import acceptance_contract
from app.services.sentiment_sampling import cumulative_consensus, sampling_queue

CITATIONS = 120
POSITIVE = 60
ROUNDS = 12


def _seed(db, project):
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"e2e-{suffix}", name="端到端引擎", vendor="测试",
                      supports_search=True, supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    question = Question(project_id=project.id, code=f"E2E-{suffix}", title="端到端题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add_all([entry, question])
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="端到端题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="端到端轮次", status=RoundStatus.RUNNING)
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

    rows = []
    for index in range(CITATIONS):
        url = f"https://site{index % 7}.example.com/a{index}.html"
        citation = MonitoringCitation(
            project_id=project.id, sample_id=sample.id, raw_url=url, normalized_url=url,
            domain=f"site{index % 7}.example.com", title=f"第 {index} 条品牌相关引用",
            page_type=CitationPageType.ARTICLE, page_type_source="rule",
            source_category=SourceCategory.NEWS_MEDIA,
            review_status=CitationReviewStatus.MANUAL_CONFIRMED, is_brand_related=True,
        )
        db.add(citation)
        rows.append(citation)
    db.commit()
    return rows


def test_contract_positive_rate_requires_consensus(db, project_factory, user_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"e2e-{suffix}")
    _seed(db, project)

    before = acceptance_contract(db, project.id, days=90, target_streak=30)
    assert before["rates"]["positive_rate"] is None
    assert before["positive_basis"]["reason"] == "not_collected"
    assert "positive_rate" in before["ready"]["missing"]

    pool: set[uuid.UUID] = set()
    for round_no in range(1, ROUNDS + 1):
        queue = sampling_queue(db, project.id, round_no=round_no, size=12, scope="brand_related", risk_scan=False)
        pool |= {uuid.UUID(item["citation_id"]) for item in queue["sample"]}
    assert len(pool) >= 50, f"抽样池仅 {len(pool)} 条，不足以验证 50 条阈值"

    # 第一轮标注：只有一个人标，契约不应出率
    ordered = sorted(pool, key=str)

    def polarity_for(index: int) -> SentimentPolarity:
        return SentimentPolarity.POSITIVE if index < POSITIVE else SentimentPolarity.NEUTRAL

    labeler_a = user_factory(f"e2e-a-{suffix}")
    for index, citation_id in enumerate(ordered):
        db.add(SentimentLabel(project_id=project.id, citation_id=citation_id,
                              polarity=polarity_for(index), labeled_by=labeler_a.id,
                              labeled_at=datetime.now(UTC)))
    db.commit()
    single = acceptance_contract(db, project.id, days=90, target_streak=30)
    assert single["rates"]["positive_rate"] is None
    assert single["positive_basis"]["reason"] == "insufficient_consensus"
    assert single["positive_basis"]["consensus_total"] == 0

    # 第二个人同档标注：共识成立
    labeler_b = user_factory(f"e2e-b-{suffix}")
    for index, citation_id in enumerate(ordered):
        db.add(SentimentLabel(project_id=project.id, citation_id=citation_id,
                              polarity=polarity_for(index), labeled_by=labeler_b.id,
                              labeled_at=datetime.now(UTC)))
    db.commit()

    consensus = cumulative_consensus(db, project.id, size=12, scope="brand_related", max_rounds=ROUNDS)
    assert consensus["consensus_total"] == len(pool)
    assert consensus["counts"]["positive"] == POSITIVE
    assert consensus["disputed"] == 0

    after = acceptance_contract(db, project.id, days=90, target_streak=30)
    expected = round(POSITIVE / len(pool), 4)
    assert after["rates"]["positive_rate"] == expected
    assert after["positive_basis"]["mode"] == "cumulative_consensus"
    assert after["positive_basis"]["consensus_total"] == len(pool)
    assert after["positive_basis"]["reason"] is None
    assert "positive_rate" not in after["ready"]["missing"]
    # 三率齐全；连续采集天数取决于真实采集节奏，不在本用例里假定
    assert after["ready"]["rates_present"] is True
    assert after["ready"]["missing"] == []
    assert after["ready"]["streak_ok"] is False  # 测试数据只有一天，连续 30 天不可能达成

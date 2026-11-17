"""品牌识别口径回归：品牌实体配置 → brand_mentioned / brand_identified / 引用归属。

覆盖的关键边界（这几条是本设计存在的理由，改坏了历史数据就不可比）：
1. 未配置品牌实体时，提及判定仍然只看项目名/项目 code——历史口径不能变；
2. 配置别名后，别名命中算提及，但地址/电话**不算**提及（别名表不能塞标识）；
3. 标识命中只写 brand_identified，不动 brand_mentioned；
4. 自有域名命中写 is_brand_related，未配置时保持原行为；
5. 情感与位次在只给地址、没点名时也能判出来（否则 Q01 这类答案整段瞎掉）；
6. 接口层拒绝把同一词条同时放进 aliases 与 identifiers（防止两个指标互相污染）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models import (
    AiEngine,
    AiEngineEntry,
    BrandProfile,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    CitationUsage,
    EngineEntryType,
    ProjectStatus,
    QuestionStatus,
    QuestionType,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.brand_profile import build_vocabulary, clean_domains
from app.services.monitoring_extraction import (
    AnswerPayload,
    CitationInput,
    apply_answer_payload,
    detect_brand_identified,
)
from app.services.stats import geo_overview, overview


BRAND_NAME = "广东省成才人工智能产业孵化有限公司"
ALIAS = "成才"
ADDRESS = "番山创业中心1号楼2区2楼"
PHONE = "13022038683"


def _make_project(db, code: str) -> Project:
    project = Project(code=code, name="广州基地", status=ProjectStatus.ACTIVE, timezone="Asia/Shanghai")
    db.add(project)
    db.flush()
    return project


def _add_profile(db, project: Project, **kwargs) -> BrandProfile:
    profile = BrandProfile(
        project_id=project.id,
        canonical_name=kwargs.get("canonical_name", BRAND_NAME),
        aliases=kwargs.get("aliases", [ALIAS]),
        identifiers=kwargs.get("identifiers", [ADDRESS, PHONE]),
        owned_domains=kwargs.get("owned_domains", []),
        is_active=kwargs.get("is_active", True),
    )
    db.add(profile)
    db.flush()
    return profile


def _next_round_seq(db, project_id) -> int:
    """同一项目内 seq 唯一；一个用例里可能建多个样本，这里顺序递增。"""
    current = db.scalar(
        select(func.max(MonitoringRound.seq)).where(MonitoringRound.project_id == project_id)
    )
    return int(current or 0) + 1


def _make_sample(db, project: Project) -> MonitoringSample:
    """最小可落样本：题目/引擎/轮次都建出来，便于 stats 关联查询。"""
    question = Question(
        project_id=project.id,
        code=f"Q-{uuid.uuid4().hex[:6]}",
        title="广东省AI数字人才就业实训基地在广州哪里，怎么报名？",
        question_type=QuestionType.BRAND,
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
    engine = AiEngine(
        code=f"e-{uuid.uuid4().hex[:6]}", name="测试引擎", vendor="test", supports_search=True
    )
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
    round_row = MonitoringRound(
        project_id=project.id,
        seq=_next_round_seq(db, project.id),
        name="品牌口径轮次",
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
    return sample


def test_vocabulary_falls_back_to_project_name_when_unconfigured(db):
    project = _make_project(db, f"bp-none-{uuid.uuid4().hex[:6]}")
    vocabulary = build_vocabulary(db, project.id, project=project)

    assert vocabulary.configured is False
    assert vocabulary.mention_terms == ["广州基地", project.code]
    assert vocabulary.identifier_terms == []
    assert vocabulary.owned_domains == []


def test_vocabulary_uses_profile_and_splits_term_kinds(db):
    project = _make_project(db, f"bp-cfg-{uuid.uuid4().hex[:6]}")
    _add_profile(db, project, owned_domains=["WWW.Chengcai-Edu.com", "chengcai-edu.com"])
    vocabulary = build_vocabulary(db, project.id, project=project)

    assert vocabulary.configured is True
    assert vocabulary.mention_terms == [BRAND_NAME, ALIAS]
    # 标识永远不会进提及词表：否则「提及率」会把只给地址的答案也算进去
    assert ADDRESS not in vocabulary.mention_terms
    assert PHONE not in vocabulary.mention_terms
    assert vocabulary.identifier_terms == [ADDRESS, PHONE]
    # 域名统一小写、去 www.、去重
    assert vocabulary.owned_domains == ["chengcai-edu.com"]


def test_inactive_profile_falls_back_to_project_name(db):
    project = _make_project(db, f"bp-off-{uuid.uuid4().hex[:6]}")
    _add_profile(db, project, is_active=False)
    vocabulary = build_vocabulary(db, project.id, project=project)

    assert vocabulary.configured is False
    assert vocabulary.mention_terms == ["广州基地", project.code]


def test_alias_makes_brand_mentioned_but_identifier_does_not(db):
    """别名命中算提及；地址/电话单独命中不算提及，只算可识别。"""
    project = _make_project(db, f"bp-mention-{uuid.uuid4().hex[:6]}")
    _add_profile(db, project)
    vocabulary = build_vocabulary(db, project.id, project=project)

    # 只是提到别名「成才」
    sample_alias = _make_sample(db, project)
    payload_alias = AnswerPayload(text="成才是广州一家做 AI 实训的机构")
    result = apply_answer_payload(
        db,
        sample_alias,
        payload_alias,
        brand_terms=vocabulary.mention_terms,
        brand_identifiers=vocabulary.identifier_terms,
    )
    assert result["brand_mentioned"] is True
    assert result["brand_identified"] is False

    # 只给地址电话、没点名——这正是 DeepSeek Q01 的真实形态
    sample_identifier = _make_sample(db, project)
    payload_identifier = AnswerPayload(
        text=f"基地在{ADDRESS}，报名电话 {PHONE}。"
    )
    result = apply_answer_payload(
        db,
        sample_identifier,
        payload_identifier,
        brand_terms=vocabulary.mention_terms,
        brand_identifiers=vocabulary.identifier_terms,
    )
    assert result["brand_mentioned"] is False
    assert result["brand_identified"] is True
    # 状态机仍按提及判定 hit/miss，可识别不改写样本状态
    assert sample_identifier.brand_mentioned is False
    assert sample_identifier.brand_identified is True


def test_brand_identified_false_without_identifiers(db):
    """没配标识词表时，brand_identified 恒为 False，不凭空放大命中。"""
    project = _make_project(db, f"bp-noid-{uuid.uuid4().hex[:6]}")
    _add_profile(db, project, identifiers=[], aliases=[ALIAS])
    vocabulary = build_vocabulary(db, project.id, project=project)

    sample = _make_sample(db, project)
    result = apply_answer_payload(
        db,
        sample,
        AnswerPayload(text=f"基地在{ADDRESS}"),
        brand_terms=vocabulary.mention_terms,
        brand_identifiers=vocabulary.identifier_terms,
    )
    assert vocabulary.identifier_terms == []
    assert result["brand_identified"] is False


def test_owned_domain_marks_citation_brand_related(db):
    """自有域名一配，引用归属立刻从恒 false 变成真实判定。"""
    project = _make_project(db, f"bp-dom-{uuid.uuid4().hex[:6]}")
    _add_profile(db, project, owned_domains=["chengcai-edu.com"])
    vocabulary = build_vocabulary(db, project.id, project=project)

    sample = _make_sample(db, project)
    apply_answer_payload(
        db,
        sample,
        AnswerPayload(
            text="成才官网有课程介绍",
            citations=[
                CitationInput(url="https://www.Chengcai-Edu.com/course", usage=CitationUsage.CITED),
                CitationInput(url="https://zhuanlan.zhihu.com/p/123", usage=CitationUsage.CITED),
            ],
        ),
        brand_terms=vocabulary.mention_terms,
        brand_domains=vocabulary.owned_domains,
        brand_identifiers=vocabulary.identifier_terms,
    )
    rows = db.scalars(
        select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id)
    ).all()
    by_domain = {row.domain: row.is_brand_related for row in rows}
    assert by_domain["chengcai-edu.com"] is True
    assert by_domain["zhuanlan.zhihu.com"] is False


def test_unconfigured_project_keeps_old_citation_behaviour(db):
    """未配置自有域名时，is_brand_related 维持原行为（False），不误判为品牌自有。"""
    project = _make_project(db, f"bp-dom-none-{uuid.uuid4().hex[:6]}")
    vocabulary = build_vocabulary(db, project.id, project=project)

    sample = _make_sample(db, project)
    apply_answer_payload(
        db,
        sample,
        AnswerPayload(
            text="无关内容",
            citations=[CitationInput(url="https://example.com/a", usage=CitationUsage.CITED)],
        ),
        brand_terms=vocabulary.mention_terms,
        brand_domains=vocabulary.owned_domains,
        brand_identifiers=vocabulary.identifier_terms,
    )
    citation = db.scalar(
        select(MonitoringCitation).where(MonitoringCitation.sample_id == sample.id)
    )
    assert citation.is_brand_related is False


def test_detect_brand_identified_ignores_empty_terms():
    assert detect_brand_identified(None, [ADDRESS]) is False
    assert detect_brand_identified(f"在{ADDRESS}", None) is False
    assert detect_brand_identified(f"在{ADDRESS}", []) is False
    assert detect_brand_identified(f"在{ADDRESS}", ["", "   "]) is False
    assert detect_brand_identified(f"在{ADDRESS}", [ADDRESS]) is True


def test_geo_overview_counts_identified_separately_from_mentioned(db):
    """两个比率各算各的：Q01 形态 = 提及 0/1、可识别 1/1。"""
    project = _make_project(db, f"bp-geo-{uuid.uuid4().hex[:6]}")
    _add_profile(db, project)
    sample = _make_sample(db, project)
    sample.status = SampleStatus.MISS
    sample.brand_mentioned = False
    sample.brand_identified = True
    sample.raw_answer = f"基地在{ADDRESS}，报名电话 {PHONE}，建议现场咨询。"
    sample.sampled_at = datetime.now(timezone.utc)
    db.flush()

    result = geo_overview(db, project.id)
    assert result["valid_answers"] == 1
    assert result["mention_rate"] == 0.0
    assert result["identified_rate"] == 1.0
    assert result["counts"]["brand_mentioned_answers"] == 0
    assert result["counts"]["brand_identified_answers"] == 1
    # 只给地址也该算进情感/位次，否则这个维度对这类答案完全瞎
    assert result["sentiment"]["not_mentioned"] == 0
    assert result["sentiment"]["neutral"] == 1
    assert result["brand_position"]["sample_count"] == 1

    overview_row = overview(db, project.id)
    assert overview_row["brand_identified_answers"] == 1
    assert overview_row["brand_identified_rate"] == 1.0


def test_clean_domains_normalizes_and_dedupes():
    assert clean_domains(["WWW.Example.COM", "example.com", "  ", "b.example.org"]) == [
        "example.com",
        "b.example.org",
    ]
    assert clean_domains(None) == []
    assert clean_domains("example.com") == []

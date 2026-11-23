"""品牌相关候选：只写 true、只碰已复核行、预览不写库。

钉住三条：
1. 标题/域名命中品牌词表的已复核引用才进候选；
2. preview 不改库，apply 才写，且只写 true；
3. auto 状态（未经人工复核）的行一律不动。
"""

import uuid
from datetime import UTC, datetime

from app.models import (
    AiEngine,
    AiEngineEntry,
    BrandProfile,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    CitationPageType,
    CitationReviewStatus,
    EngineEntryType,
    QuestionType,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    SourceCategory,
    TaskStatus,
)
from app.services.brand_related_candidates import brand_related_candidates
from app.services.page_title_backfill import FetchResult
from app.services.source_category_propagation import source_category_candidates
from app.services.source_domain_registry import classify_domains, domain_overview
from app.services import source_domain_evidence as evidence_service


def _seed(db, project):
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"br-{suffix}", name="品牌引擎", vendor="测试", supports_search=True,
                      supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    db.add(entry)
    question = Question(project_id=project.id, code=f"BR-{suffix}", title="品牌题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="品牌题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="品牌轮次", status=RoundStatus.RUNNING)
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

    rows = [
        ("https://www.zgceo.cn/a.html", "广东省成才人工智能产业孵化有限公司实训基地怎么样", CitationReviewStatus.MANUAL_CONFIRMED),
        ("https://example.com/b.html", "普通行业文章，没有品牌词", CitationReviewStatus.MANUAL_CONFIRMED),
        ("https://example.com/c.html", "成才基地未复核", CitationReviewStatus.AUTO),
    ]
    created = []
    for url, title, status in rows:
        cit = MonitoringCitation(
            project_id=project.id, sample_id=sample.id, raw_url=url, normalized_url=url,
            domain=url.split("/")[2], title=title, page_type=CitationPageType.ARTICLE, page_type_source="rule",
            source_category=SourceCategory.NEWS_MEDIA, review_status=status, is_brand_related=False,
        )
        db.add(cit)
        created.append(cit)
    db.commit()
    return created


def test_classify_domain_applies_whole_site(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cd-{suffix}")
    rows = _seed(db, project)
    for row in rows:
        row.review_status = CitationReviewStatus.MANUAL_CONFIRMED
        row.source_category = SourceCategory.UNKNOWN
    db.commit()

    result = classify_domains(db, project.id, [{"site": rows[0].domain, "category": "news_media", "note": "首页自称新闻媒体"}])
    assert result["changed"] >= 1
    db.refresh(rows[0])
    assert rows[0].source_category == SourceCategory.NEWS_MEDIA
    # 判回 unknown 被拒
    rejected = classify_domains(db, project.id, [{"site": rows[0].domain, "category": "unknown"}])
    assert rejected["changed"] == 0
    overview = domain_overview(db, project.id)
    site_row = next(e for e in overview["domains"] if e["site"] == "zgceo.cn")
    assert site_row["status"] == "settled"


def test_domain_evidence_is_cached_not_inferred(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"ev-{suffix}")
    rows = _seed(db, project)
    for row in rows:
        row.review_status = CitationReviewStatus.MANUAL_CONFIRMED
        row.source_category = SourceCategory.UNKNOWN
    db.commit()

    calls: list[str] = []

    def fake_fetch(url: str, timeout: float = 8.0):
        calls.append(url)
        if url.startswith("https://") and url.endswith("/"):
            return FetchResult(status="ok", title=f"{url} 站点标题", snippet="站点描述")
        return FetchResult(status="blocked", detail="403")

    monkeypatch.setattr(evidence_service, "fetch_title", fake_fetch)
    first = evidence_service.collect_domain_evidence(db, project.id, refresh=True)
    assert first["fetched"] >= 1
    # 第二次不刷新就不应重复抓取
    calls.clear()
    second = evidence_service.collect_domain_evidence(db, project.id)
    assert second["fetched"] == 0
    assert not calls

    overview = evidence_service.evidence_map(db, project.id)
    assert any("站点标题" in (item["title"] or "") for item in overview.values())


def test_source_category_propagation(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"scp-{suffix}")
    rows = _seed(db, project)
    # 同站一条已知类别（新闻媒体），同站另一条仍是 unknown
    rows[0].source_category = SourceCategory.NEWS_MEDIA
    rows[1].domain = rows[0].domain
    rows[1].raw_url = "https://www.zgceo.cn/b.html"
    rows[1].normalized_url = rows[1].raw_url
    rows[1].source_category = SourceCategory.UNKNOWN
    db.commit()

    preview = source_category_candidates(db, project.id, apply=False)
    assert preview["scope"]["sites_with_evidence"] >= 1
    candidate = next(item for item in preview["candidates"] if item["site"].endswith("zgceo.cn"))
    assert candidate["category"] == "news_media"
    assert candidate["affected_citations"] >= 1
    db.refresh(rows[1])
    assert rows[1].source_category == SourceCategory.UNKNOWN  # 预览不写库

    applied = source_category_candidates(db, project.id, apply=True)
    db.refresh(rows[1])
    assert rows[1].source_category == SourceCategory.NEWS_MEDIA
    assert applied["scope"]["changed"] >= 1
    # 未知类别自身不会被「传播成」other
    db.refresh(rows[0])
    assert rows[0].source_category == SourceCategory.NEWS_MEDIA


def test_brand_related_candidates_preview_and_apply(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"brc-{suffix}")
    db.add(BrandProfile(project_id=project.id, canonical_name="广东省成才人工智能产业孵化有限公司",
                        aliases=["成才基地"]))
    db.commit()
    rows = _seed(db, project)

    preview = brand_related_candidates(db, project.id, apply=False, limit=100)
    assert preview["scope"]["candidates"] == 1
    assert preview["scope"]["changed"] == 0
    assert preview["examples"][0]["raw_url"] == "https://www.zgceo.cn/a.html"
    assert rows[0].is_brand_related is False  # 预览不写库
    assert rows[2].is_brand_related is False  # auto 行不进候选

    applied = brand_related_candidates(db, project.id, apply=True, limit=100)
    assert applied["scope"]["changed"] == 1
    db.refresh(rows[0])
    db.refresh(rows[1])
    db.refresh(rows[2])
    assert rows[0].is_brand_related is True
    assert rows[1].is_brand_related is False  # 不写 false、也不误判
    assert rows[2].is_brand_related is False

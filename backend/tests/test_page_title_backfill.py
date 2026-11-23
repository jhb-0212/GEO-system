"""标题补齐：只补 title 为空的 other 行，取不到就留空。"""

from __future__ import annotations

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
from app.services.page_title_backfill import FetchResult, backfill_titles, clean_title, parse_html


def test_parse_html_and_clean_title():
    body = (
        "<html><head><title>2026广州AI培训机构十大排名_某教育网</title>"
        '<meta name="description" content="盘点广州十家AI培训机构"></head></html>'
    )
    title, snippet = parse_html(body)
    assert title == "2026广州AI培训机构十大排名"
    assert snippet == "盘点广州十家AI培训机构"
    assert clean_title("  ") is None
    assert parse_html("<html><head></head></html>") == (None, None)


def _seed_citations(db, project) -> None:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"tb-{suffix}", name="标题引擎", vendor="测试", supports_search=True,
                      supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    db.add(entry)
    question = Question(project_id=project.id, code=f"TB-{suffix}", title="标题题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="标题题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="标题轮次", status=RoundStatus.RUNNING)
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
        ("https://example.com/a", "rule", None),
        ("https://example.com/b", "unknown", None),
        # 人工结论行不补
        ("https://example.com/c", "manual", None),
        # 已有标题不补
        ("https://example.com/d", "rule", "已有标题"),
        # 非 other 不补
        ("https://example.com/e", "rule", None),
    ]
    for url, source, title in rows:
        db.add(MonitoringCitation(
            project_id=project.id, sample_id=sample.id,
            raw_url=url, normalized_url=url, domain=url.split("/")[2], title=title,
            page_type=CitationPageType.OTHER if url not in ("https://example.com/e",) else CitationPageType.ARTICLE,
            page_type_source=source,
            source_category=SourceCategory.SOCIAL_COMMUNITY,
            review_status=CitationReviewStatus.MANUAL_CONFIRMED,
        ))
    db.commit()


def test_backfill_dry_run_and_apply(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"tb-{suffix}")
    _seed_citations(db, project)

    def fake_fetcher(url: str) -> FetchResult:
        if url.endswith("/a"):
            return FetchResult(status="ok", title="十大AI培训机构排名", snippet="榜单")
        return FetchResult(status="blocked", detail="403")

    dry = backfill_titles(db, project.id, limit=10, dry_run=True, fetcher=fake_fetcher, pause=0)
    assert dry["scope"]["candidates"] == 2  # a / b；manual、已有标题、非 other 都不算
    assert dry["scope"]["titled"] == 1
    assert dry["by_status"] == {"ok": 1, "blocked": 1}

    # 预览不写库
    row_a = db.query(MonitoringCitation).filter_by(project_id=project.id, raw_url="https://example.com/a").one()
    assert row_a.title is None

    applied = backfill_titles(db, project.id, limit=10, dry_run=False, fetcher=fake_fetcher, pause=0)
    assert applied["scope"]["titled"] == 1
    db.refresh(row_a)
    assert row_a.title == "十大AI培训机构排名"
    assert row_a.snippet == "榜单"
    # 失败的行保持空，不留假标题
    row_b = db.query(MonitoringCitation).filter_by(project_id=project.id, raw_url="https://example.com/b").one()
    assert row_b.title is None

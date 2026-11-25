"""卖点完整、品牌搜索导入、竞品信源拆表。"""

import uuid
from datetime import UTC, datetime

from app.core.security import create_access_token

from app.models import (
    AiEngine,
    AiEngineEntry,
    Competitor,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
    SellingPoint,
)
from app.models.enums import (
    CitationPageType,
    CitationReviewStatus,
    EngineEntryType,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    SourceCategory,
    TaskStatus,
)
from app.services.brand_search import brand_search_report, import_snapshots
from app.services.competitor_sources import competitor_source_report
from app.services.acceptance_contract import acceptance_contract
from app.services.dashboard_tracks import tracks_snapshot
from app.services.selling_points import selling_point_check, selling_point_summary
from app.services.source_coverage import source_coverage
from app.services.source_matrix import source_matrix
from app.services.source_tiers import source_tiers
from app.services.stats import daily_trend, weekly_trend


def test_selling_point_check_distinguishes_covered_mentioned_missing(db, project_factory):
    project = project_factory(f"sp-{uuid.uuid4().hex[:6]}")
    db.add_all([
        SellingPoint(project_id=project.id, label="小班教学", value_text="每班不超过 6 人", aliases=["小班", "精品班"]),
        SellingPoint(project_id=project.id, label="价格透明", value_text="3980 元", aliases=["价格"]),
        SellingPoint(project_id=project.id, label="免费试听", value_text="免费试听", aliases=["试听"]),
    ])
    db.commit()

    result = selling_point_check(db, project.id, "我们是小班教学，价格公开，欢迎咨询。")
    assert result["points_total"] == 3
    assert result["covered"] == 0
    assert result["mentioned"] == 2
    assert result["missing"] == 1
    assert result["status"] == "partial"


def test_selling_point_summary_counts_current_versions(db, project_factory):
    from app.models import ContentItem, ContentVersion
    from app.models.enums import ContentKind, ContentStatus

    project = project_factory(f"sp-sum-{uuid.uuid4().hex[:6]}")
    db.add(SellingPoint(project_id=project.id, label="小班教学", value_text="每班不超过 6 人", aliases=["小班"]))
    db.flush()
    item = ContentItem(project_id=project.id, kind=ContentKind.MASTER, title="卖点稿", status=ContentStatus.APPROVED)
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id, item_id=item.id, version_no=1, body="每班不超过 6 人",
        content_hash=uuid.uuid4().hex.ljust(64, "0"), status=ContentStatus.APPROVED,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.commit()

    result = selling_point_summary(db, project.id)
    assert result["summary"]["contents_total"] == 1
    assert result["points"][0]["covered"] == 1
    assert result["points"][0]["coverage"] == 1.0


def test_brand_search_import_upserts_and_reports_delta(db, project_factory):
    project = project_factory(f"bs-{uuid.uuid4().hex[:6]}")
    result = import_snapshots(db, project.id, [
        {"platform": "baidu", "date": "2026-11-01", "search_volume": 100},
        {"platform": "baidu", "date": "2026-11-02", "search_volume": "150"},
    ])
    assert result["imported"] == 2
    report = brand_search_report(db, project.id, days=365)
    row = report["platforms"][0]
    assert row["latest_volume"] == 150
    assert row["delta"] == 50
    assert row["delta_pct"] == 0.5

    again = import_snapshots(db, project.id, [
        {"platform": "baidu", "date": "2026-11-02", "search_volume": 180},
    ])
    assert again["updated"] == 1
    report = brand_search_report(db, project.id, days=365)
    assert report["platforms"][0]["latest_volume"] == 180


def _seed_competitor_citations(db, project, sampled_at: datetime | None = None):
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"cmp-{suffix}", name="竞品引擎", vendor="测试",
                      supports_search=True, supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    question = Question(project_id=project.id, code=f"CMP-{suffix}", title="竞品题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add_all([entry, question])
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="竞品题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="竞品轮次", status=RoundStatus.RUNNING)
    db.add_all([version, round_row])
    db.flush()
    task = MonitoringTask(project_id=project.id, round_id=round_row.id, question_version_id=version.id,
                          engine_entry_id=entry.id, sampling_no=1, sampling_mode=SamplingMode.SEARCH_ON,
                          status=TaskStatus.DONE)
    db.add(task)
    db.flush()
    sample = MonitoringSample(project_id=project.id, task_id=task.id, attempt_no=1,
                              status=SampleStatus.HIT, sampled_at=sampled_at or datetime.now(UTC), brand_mentioned=True)
    db.add(sample)
    db.flush()
    competitor = Competitor(project_id=project.id, name="竞品甲")
    db.add(competitor)
    db.flush()
    for domain, category, count in [
        ("zhihu.com", SourceCategory.SOCIAL_COMMUNITY, 3),
        ("gov.cn", SourceCategory.GOVERNMENT_INSTITUTION, 1),
        ("unknown.example.com", SourceCategory.UNKNOWN, 2),
    ]:
        for index in range(count):
            url = f"https://{domain}/a{index}.html"
            db.add(MonitoringCitation(
                project_id=project.id, sample_id=sample.id, competitor_id=competitor.id,
                raw_url=url, normalized_url=url, domain=domain, title="竞品引用",
                page_type=CitationPageType.ARTICLE, page_type_source="rule",
                source_category=category, review_status=CitationReviewStatus.MANUAL_CONFIRMED,
            ))
    db.commit()


def test_competitor_sources_splits_tiers_by_competitor(db, project_factory):
    project = project_factory(f"cmp-{uuid.uuid4().hex[:6]}")
    _seed_competitor_citations(db, project)
    report = competitor_source_report(db, project.id, days=90)
    assert report["summary"]["competitors"] == 1
    row = report["competitors"][0]
    assert row["citations"] == 6
    assert row["tier_counts"]["T0"] == 1
    assert row["tier_counts"]["T1"] == 3
    assert row["tier_counts"]["T3"] == 2
    assert row["high_quality_citations"] == 4
    assert row["high_quality_share"] == round(4 / 6, 4)


def test_new_metrics_share_project_timezone_calendar_window(db, project_factory):
    project = project_factory(f"tz-{uuid.uuid4().hex[:6]}")
    project.timezone = "America/New_York"
    db.commit()
    moment = datetime(2026, 11, 25, 3, 0, tzinfo=UTC)  # 纽约仍是 11-24 晚 22:00
    brand = brand_search_report(db, project.id, days=30, now=moment)
    competitor = competitor_source_report(db, project.id, days=30, now=moment)
    assert brand["end_date"] == "2026-11-24"
    assert competitor["end_date"] == brand["end_date"]
    assert brand["start_date"] == competitor["start_date"] == "2026-10-26"


def test_all_stat_windows_use_project_timezone(db, project_factory):
    from zoneinfo import ZoneInfo

    project = project_factory(f"tzall-{uuid.uuid4().hex[:6]}")
    project.timezone = "America/New_York"
    db.commit()
    moment = datetime(2026, 11, 25, 3, 0, tzinfo=UTC)  # 纽约 11-24 22:00，上海 11-25 11:00
    _seed_competitor_citations(db, project, sampled_at=moment)
    ny = ZoneInfo("America/New_York")

    daily = daily_trend(db, project.id, days=3, now=moment)
    assert daily[-1]["date"].astimezone(ny).date().isoformat() == "2026-11-24"
    assert daily[-1]["valid_answers"] == 1

    weekly = weekly_trend(db, project.id, weeks=2, now=moment)
    assert weekly[-1]["week_start"].astimezone(ny).date().isoformat() == "2026-11-23"
    assert weekly[-1]["valid_answers"] == 1

    for report in (
        source_coverage(db, project.id, days=30, now=moment),
        source_tiers(db, project.id, days=30, now=moment),
        source_matrix(db, project.id, days=30, now=moment),
    ):
        assert report["start_date"] == "2026-10-26"
        assert report["end_date"] == "2026-11-24"
    assert acceptance_contract(db, project.id, days=30, now=moment)["end_date"] == "2026-11-24"
    assert tracks_snapshot(db, project.id, days=30, now=moment)["end_date"] == "2026-11-24"


def test_selling_point_crud_and_brand_search_import_api(client, db, project_factory, user_factory, member_factory):
    project = project_factory(f"api-{uuid.uuid4().hex[:6]}")
    user = user_factory(f"sp-api-{uuid.uuid4().hex[:6]}")
    member_factory(project, user, RoleCode.EDITOR)
    headers = {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}
    metric_admin = user_factory(f"sp-metric-{uuid.uuid4().hex[:6]}")
    member_factory(project, metric_admin, RoleCode.PROJECT_ADMIN)
    metric_headers = {"Authorization": f"Bearer {create_access_token(metric_admin.id, token_version=metric_admin.token_version)}"}
    base = f"/api/v1/projects/{project.id}"

    created = client.post(f"{base}/selling-points", headers=headers, json={
        "label": "小班教学", "value_text": "每班不超过 6 人", "aliases": ["小班"], "required": True,
    })
    assert created.status_code == 201, created.text
    point_id = created.json()["data"]["id"]
    listed = client.get(f"{base}/selling-points", headers=headers)
    assert listed.status_code == 200
    assert [row["label"] for row in listed.json()["data"]] == ["小班教学"]
    updated = client.patch(f"{base}/selling-points/{point_id}", headers=headers, json={"is_active": False})
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["is_active"] is False

    imported = client.post(f"{base}/stats/brand-search/import", headers=metric_headers, json={
        "rows": [{"platform": "baidu", "date": "2026-11-01", "search_volume": 120}], "source": "csv",
    })
    assert imported.status_code == 200, imported.text
    assert imported.json()["data"]["imported"] == 1
    report = client.get(f"{base}/stats/brand-search?days=365", headers=headers)
    assert report.status_code == 200
    assert report.json()["data"]["platforms"][0]["latest_volume"] == 120

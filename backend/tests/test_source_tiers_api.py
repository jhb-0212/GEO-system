"""信源分级（T0–T3）+ 多源交叉验证。

钉住五条：
1. 定档按优先级走：自有域名/政府/院校 → T0，白名单 → T1/T2，其余 → T3，每条都带命中规则；
2. 未复核引用不进任何分母；
3. 交叉验证按回答计数：同站多页只算一个来源；
4. 多高权重来源 = 一条回答里至少两个不同 T0/T1 站；
5. 分级绝不做加权总分，只输出档位、条数、份额。
"""

import uuid
from datetime import UTC, datetime

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    BrandProfile,
    Competitor,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
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
from app.services.source_tiers import classify


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _seed(db, project, *, brand_samples: int = 2) -> None:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"t-{suffix}", name="分级引擎", vendor="测试", supports_search=True,
                      supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    db.add(entry)
    question = Question(project_id=project.id, code=f"T-{suffix}", title="分级题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="分级题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="分级轮次", status=RoundStatus.RUNNING)
    db.add_all([version, round_row])
    db.flush()
    task = MonitoringTask(project_id=project.id, round_id=round_row.id, question_version_id=version.id,
                          engine_entry_id=entry.id, sampling_no=1, sampling_mode=SamplingMode.SEARCH_ON,
                          status=TaskStatus.DONE)
    db.add(task)
    db.flush()

    db.add(BrandProfile(project_id=project.id, canonical_name="本品牌", owned_domains=["gdccai.com"]))
    rival = Competitor(project_id=project.id, name="竞品乙", is_active=True)
    db.add(rival)
    db.flush()

    samples = []
    for index in range(brand_samples + 1):
        sample = MonitoringSample(project_id=project.id, task_id=task.id, attempt_no=index + 1,
                                 status=SampleStatus.HIT, sampled_at=datetime.now(UTC),
                                 brand_mentioned=index < brand_samples)
        db.add(sample)
        samples.append(sample)
    db.flush()

    # 回答 1：自有站 + 知乎 → 两个来源、两个高权重档（T0+T1）
    # 回答 2：知乎两页 → 同一站只算一个来源
    # 回答 3：只有竞品被引 → 不进交叉验证分母
    citations = [
        (samples[0].id, "gdccai.com", SourceCategory.BRAND_OWNED, None, CitationReviewStatus.MANUAL_CONFIRMED),
        (samples[0].id, "zhihu.com", SourceCategory.SOCIAL_COMMUNITY, None, CitationReviewStatus.MANUAL_CONFIRMED),
        (samples[1].id, "zhihu.com", SourceCategory.SOCIAL_COMMUNITY, None, CitationReviewStatus.MANUAL_CONFIRMED),
        (samples[1].id, "zhuanlan.zhihu.com", SourceCategory.SOCIAL_COMMUNITY, None, CitationReviewStatus.MANUAL_CONFIRMED),
        (samples[2].id, "zhihu.com", SourceCategory.SOCIAL_COMMUNITY, rival.id, CitationReviewStatus.MANUAL_CONFIRMED),
        # 未复核：不进分母
        (samples[0].id, "weibo.com", SourceCategory.SOCIAL_COMMUNITY, None, CitationReviewStatus.AUTO),
    ]
    for sample_id, domain, category, competitor_id, review in citations:
        db.add(MonitoringCitation(
            project_id=project.id, sample_id=sample_id,
            raw_url=f"https://{domain}/a/{suffix}", normalized_url=f"{domain}/a/{suffix}",
            domain=domain, is_brand_related=competitor_id is None,
            source_category=category, competitor_id=competitor_id, review_status=review,
        ))
    db.flush()


def test_classify_rules_are_ordered_and_explained():
    owned = classify("gdccai.com", owned_domains=["gdccai.com"])
    assert owned["tier"] == "T0" and owned["tier_rule"] == "owned_domain"

    gov = classify("www.gz.gov.cn")
    assert gov["tier"] == "T0" and gov["tier_rule"] == "domain:gov_cn"

    school = classify("gdut.edu.cn", source_category=SourceCategory.EDUCATION_INSTITUTION)
    assert school["tier"] == "T0" and school["tier_rule"] == "domain:edu_cn"

    # 机构类别但域名不是官方域：民办培训站进 T2，不冒充 T0
    training = classify("qinxue365.com", source_category=SourceCategory.EDUCATION_INSTITUTION)
    assert training["tier"] == "T2" and training["tier_rule"] == "category:institution:non_official_domain"

    wechat = classify("mp.weixin.qq.com")
    assert wechat["tier"] == "T1" and wechat["tier_rule"] == "whitelist:T1"
    assert "weixin.qq.com" in wechat["tier_reason"]

    portal = classify("www.163.com")
    assert portal["tier"] == "T2"

    longtail = classify("some-personal-blog.example")
    assert longtail["tier"] == "T3" and longtail["tier_rule"] == "default:T3"

    # 白名单优先于「参考站类别」：百度百科条目页走 T1
    baike = classify("baike.baidu.com", source_category=SourceCategory.REFERENCE)
    assert baike["tier"] == "T1"


def test_source_tiers_counts_and_cross_validation(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"t-{suffix}")
    viewer = user_factory(f"t-v-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    _seed(db, project)

    response = client.get(f"/api/v1/projects/{project.id}/stats/source-tiers?days=90", headers=_auth(viewer))
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    # 5 条已复核引用（weibo 是 auto），2 个域名
    assert data["scope"]["reviewed_citations"] == 5
    assert data["scope"]["reviewed_domains"] == 2

    tiers = {row["tier"]: row for row in data["tiers"]}
    # 自有站 1 条 T0；zhihu.com 4 条 T1（zhuanlan 归同站同档）
    assert tiers["T0"]["citations"] == 1 and tiers["T0"]["domains"] == 1
    assert tiers["T1"]["citations"] == 4 and tiers["T1"]["domains"] == 1
    assert tiers["T2"]["citations"] == 0 and tiers["T3"]["citations"] == 0
    assert tiers["T0"]["citation_share"] == round(1 / 5, 4)

    by_domain = {row["domain"]: row for row in data["domains"]}
    assert by_domain["zhihu.com"]["tier"] == "T1"
    assert by_domain["zhihu.com"]["tier_rule"] == "whitelist:T1"
    assert by_domain["gdccai.com"]["tier"] == "T0"
    assert "weibo.com" not in by_domain

    cross = data["cross_validation"]
    # 只有 2 条回答有我方引用；同站多页不重复计数
    assert cross["brand_cited_answers"] == 2
    assert cross["single_source_answers"] == 1
    assert cross["multi_source_answers"] == 1
    assert cross["tier01_supported_answers"] == 2
    assert cross["multi_high_tier_answers"] == 1
    assert cross["multi_source_rate"] == 0.5
    assert cross["multi_high_tier_rate"] == 0.5

    # 规则清单对外可核，档位定义齐全
    assert [row["rule"] for row in data["rules"]][0] == "owned_domain"
    assert {row["tier"] for row in data["tiers"]} == {"T0", "T1", "T2", "T3"}
    # 明确不做加权总分
    assert any("不做加权总分" in note for note in data["notes"])


def test_source_tiers_empty_project(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"t-empty-{suffix}")
    viewer = user_factory(f"t-empty-v-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    response = client.get(f"/api/v1/projects/{project.id}/stats/source-tiers", headers=_auth(viewer))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scope"]["reviewed_citations"] == 0
    assert data["domains"] == []
    assert all(row["citation_share"] is None for row in data["tiers"])
    assert data["cross_validation"]["multi_source_rate"] is None

"""信源 × 内容形态矩阵。

钉住四条：
1. 按站点交叉 page_type，只算已复核引用；
2. 同站折叠后多页只累加条数，主形态与份额按条数算；
3. 档位过滤生效（默认 T0/T1/T2，T3 需显式请求）；
4. 状态区分自有 / 已覆盖 / 缺口 / 未被触碰，不产出任何形态匹配评分。
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


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _seed(db, project) -> None:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"mx-{suffix}", name="矩阵引擎", vendor="测试", supports_search=True,
                      supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    db.add(entry)
    question = Question(project_id=project.id, code=f"MX-{suffix}", title="矩阵题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="矩阵题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="矩阵轮次", status=RoundStatus.RUNNING)
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
    rival = Competitor(project_id=project.id, name="竞品丙", is_active=True)
    db.add(rival)
    db.flush()

    # 知乎：文章 2 条（我方）、榜单 1 条（我方）、问答 1 条（竞品）→ 主形态 article 50%
    # 163：文章 2 条（我方，未发过）→ untouched
    # 长尾站：视频 1 条（我方）→ 默认档位过滤掉
    citations = [
        ("zhihu.com", CitationPageType.ARTICLE, None, CitationReviewStatus.MANUAL_CONFIRMED, 2),
        ("zhihu.com", CitationPageType.LISTICLE, None, CitationReviewStatus.MANUAL_CONFIRMED, 1),
        ("zhihu.com", CitationPageType.FORUM_OR_QA, rival.id, CitationReviewStatus.MANUAL_CONFIRMED, 1),
        ("163.com", CitationPageType.ARTICLE, None, CitationReviewStatus.MANUAL_CONFIRMED, 2),
        ("longtail-blog.example", CitationPageType.VIDEO, None, CitationReviewStatus.MANUAL_CONFIRMED, 1),
        ("zhihu.com", CitationPageType.ARTICLE, None, CitationReviewStatus.AUTO, 1),  # 未复核不计
    ]
    for domain, page_type, competitor_id, review, count in citations:
        for index in range(count):
            db.add(MonitoringCitation(
                project_id=project.id, sample_id=sample.id,
                raw_url=f"https://{domain}/p/{suffix}-{page_type.value}-{index}",
                normalized_url=f"{domain}/p/{suffix}-{page_type.value}-{index}",
                domain=domain, is_brand_related=competitor_id is None, page_type=page_type,
                source_category=SourceCategory.SOCIAL_COMMUNITY if "zhihu" in domain else SourceCategory.OTHER,
                competitor_id=competitor_id, review_status=review,
            ))
    db.flush()


def test_source_matrix_groups_forms_and_filters_tiers(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mx-{suffix}")
    viewer = user_factory(f"mx-v-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    _seed(db, project)

    response = client.get(
        f"/api/v1/projects/{project.id}/stats/source-matrix?days=90&limit=20", headers=_auth(viewer)
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    # 7 条已复核引用（auto 那条不算）
    assert data["scope"]["reviewed_citations"] == 7
    assert data["scope"]["tiers"] == ["T0", "T1", "T2"]
    # 默认档位过滤掉长尾站：只剩知乎(T1) 与 163(T2)
    by_domain = {row["domain"]: row for row in data["domains"]}
    assert set(by_domain) == {"zhihu.com", "163.com"}

    zhihu = by_domain["zhihu.com"]
    assert zhihu["tier"] == "T1"
    assert zhihu["citations"] == 4
    assert zhihu["top_form"] == "article"
    assert zhihu["top_form_share"] == 0.5
    forms = {row["form"]: row["citations"] for row in zhihu["forms"]}
    assert forms == {"article": 2, "listicle": 1, "forum_or_qa": 1}
    # 竞品在该站被引、我们没有回执 → 缺口
    assert zhihu["competitor_citations"] == 1
    assert zhihu["status"] == "gap"

    assert by_domain["163.com"]["tier"] == "T2"
    assert by_domain["163.com"]["status"] == "untouched"

    # 全局形态分布含所有已复核引用（含被档位过滤掉的长尾视频）
    form_totals = {row["form"]: row["citations"] for row in data["forms"]}
    assert form_totals["article"] == 4
    assert form_totals["video"] == 1

    # T3 显式请求时才出现
    t3 = client.get(
        f"/api/v1/projects/{project.id}/stats/source-matrix?days=90&tiers=T3", headers=_auth(viewer)
    ).json()["data"]
    assert {row["domain"] for row in t3["domains"]} == {"longtail-blog.example"}
    assert t3["domains"][0]["top_form"] == "video"

    # 非法档位被忽略并回显，不报 500
    bad = client.get(
        f"/api/v1/projects/{project.id}/stats/source-matrix?days=90&tiers=T9", headers=_auth(viewer)
    ).json()["data"]
    assert bad["scope"]["invalid_tiers"] == ["T9"]
    assert bad["scope"]["tiers"] == ["T1"]


def test_source_matrix_empty_project(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mx-empty-{suffix}")
    viewer = user_factory(f"mx-empty-v-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    response = client.get(f"/api/v1/projects/{project.id}/stats/source-matrix", headers=_auth(viewer))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scope"]["reviewed_citations"] == 0
    assert data["domains"] == []
    assert data["forms"] == []

"""M3 三分 + M2 样本份额：把已有数据换角度算，不改采集与发布路径。

钉住四条：
1. cited 只在「点名提及 + 基地相关且已复核引用」同时成立时计 1；
2. 三分互斥且相加等于 valid_answers，不能让三档出现重叠或漏记；
3. 没有可观测引用的引擎（supports_citation=False）直接落 mentioned_only，不污染 cited；
4. SoV 样本份额的分母是「提到品牌或任一竞品的去重样本」，且品牌与竞品排在同一个列表里。
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
    MonitoringCompetitorMention,
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
    TaskStatus,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _setup(project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"three-{suffix}")
    viewer = user_factory(f"three-v-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    db_engine = None
    return project, viewer, suffix


def _seed(db, project, suffix, *, supports_citation=True):
    """造三条有效回答：提及+引用 / 提及无引用 / 未提及；并在第一条里挂一个竞品。"""
    engine = AiEngine(
        code=f"m3-{suffix}", name="M3 引擎", vendor="测试",
        supports_search=True, supports_citation=supports_citation, is_active=True,
    )
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端",
        supports_search=True, is_active=True,
    )
    db.add(entry)
    db.add(BrandProfile(project_id=project.id, canonical_name=f"本品牌{suffix}"))
    competitor = Competitor(project_id=project.id, name=f"竞品{suffix}", is_active=True)
    db.add(competitor)
    question = Question(
        project_id=project.id, code=f"Q-{suffix}", title="三分测试",
        question_type=QuestionType.GENERAL, status="active", current_version_no=1,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="三分测试")
    db.add(version)
    db.flush()
    round_row = MonitoringRound(project_id=project.id, seq=1, name="三分轮次", status=RoundStatus.RUNNING)
    db.add(round_row)
    db.flush()

    samples = []
    for sampling_no, mentioned in ((1, True), (2, True), (3, False)):
        task = MonitoringTask(
            project_id=project.id, round_id=round_row.id, question_version_id=version.id,
            engine_entry_id=entry.id, sampling_no=sampling_no,
            sampling_mode=SamplingMode.SEARCH_ON, status=TaskStatus.DONE,
        )
        db.add(task)
        db.flush()
        sample = MonitoringSample(
            project_id=project.id, task_id=task.id, attempt_no=1, status=SampleStatus.HIT,
            sampled_at=datetime.now(UTC), brand_mentioned=mentioned,
        )
        db.add(sample)
        db.flush()
        samples.append(sample)

    # 第 1 条样本：一条已复核的基地相关引用（带 URL），才算 cited
    db.add(MonitoringCitation(
        project_id=project.id, sample_id=samples[0].id,
        raw_url=f"https://gdccai.com/faq/{suffix}", normalized_url=f"gdccai.com/faq/{suffix}",
        domain="gdccai.com", is_brand_related=True,
        review_status=CitationReviewStatus.MANUAL_CONFIRMED,
    ))
    # 第 2 条样本只给一条未复核的引用，不能算 cited
    db.add(MonitoringCitation(
        project_id=project.id, sample_id=samples[1].id,
        raw_url=f"https://gdccai.com/raw/{suffix}", normalized_url=f"gdccai.com/raw/{suffix}",
        domain="gdccai.com", is_brand_related=True,
        review_status=CitationReviewStatus.AUTO,
    ))
    # 竞品与品牌同现在第 1 条样本：样本份额分母要按并集去重
    db.add(MonitoringCompetitorMention(
        project_id=project.id, competitor_id=competitor.id, sample_id=samples[0].id,
    ))
    db.flush()


def test_three_state_is_mutually_exclusive(
    client, db, project_factory, user_factory, member_factory
):
    project, viewer, suffix = _setup(project_factory, user_factory, member_factory)
    _seed(db, project, suffix)

    response = client.get(
        f"/api/v1/projects/{project.id}/stats/overview?question_type=general", headers=_auth(viewer)
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["valid_answers"] == 3
    assert data["brand_cited_answers"] == 1
    state = data["three_state"]
    assert state == {"cited": 1, "mentioned_only": 1, "absent": 1, "denominator": 3}
    assert state["cited"] + state["mentioned_only"] + state["absent"] == data["valid_answers"]
    assert data["brand_cited_rate"] == round(1 / 3, 4)


def test_engine_without_citation_surface_never_counts_as_cited(
    client, db, project_factory, user_factory, member_factory
):
    project, viewer, suffix = _setup(project_factory, user_factory, member_factory)
    _seed(db, project, suffix, supports_citation=False)

    response = client.get(
        f"/api/v1/projects/{project.id}/stats/overview?question_type=general", headers=_auth(viewer)
    )
    data = response.json()["data"]
    # 该引擎不展示引用来源，cited 一律为 0，不能把"没看到链接"当成"没被引用"
    assert data["brand_cited_answers"] == 0
    assert data["three_state"]["cited"] == 0
    assert data["three_state"]["mentioned_only"] == 2
    assert data["citation_observable_answers"] == 0


def test_sov_detail_lists_brand_and_competitors_on_one_scale(
    client, db, project_factory, user_factory, member_factory
):
    project, viewer, suffix = _setup(project_factory, user_factory, member_factory)
    _seed(db, project, suffix)

    response = client.get(f"/api/v1/projects/{project.id}/stats/geo", headers=_auth(viewer))
    assert response.status_code == 200, response.text
    detail = response.json()["data"]["sov_detail"]
    assert detail["denominator_samples"] == 2
    entities = {row["entity"]: row for row in detail["entities"]}
    brand = entities[f"本品牌{suffix}"]
    rival = entities[f"竞品{suffix}"]
    assert brand["kind"] == "brand"
    assert brand["mentioned_samples"] == 2
    assert rival["mentioned_samples"] == 1
    assert brand["share"] == 1.0
    assert rival["share"] == 0.5
    assert "超过 100%" in detail["note"]

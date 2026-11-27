"""情感抽样盲评：抽样可复算、双人各写各的、预排序不进比率。

钉住四条：
1. 同一人同一引用只留一条标注，不同人可以各写一条（迁移已放开唯一键）；
2. 抽样顺序只由「轮次 + 引用 id」哈希决定，重跑得到同一批；
3. 只有两人以上同档才算共识，分歧留在 disputed 不外推；
4. 共识不足 50 条不出正向率，预排序命中词不产生任何比率。
"""

import uuid
from datetime import UTC, datetime

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    SentimentLabel,
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
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    SentimentPolarity,
    SourceCategory,
    TaskStatus,
)
from app.services.sentiment_sampling import MIN_REPORT, consensus, cumulative_consensus, sampling_queue


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _seed(db, project) -> list[MonitoringCitation]:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"ss-{suffix}", name="抽样引擎", vendor="测试", supports_search=True,
                      supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    db.add(entry)
    question = Question(project_id=project.id, code=f"SS-{suffix}", title="抽样题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="抽样题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="抽样轮次", status=RoundStatus.RUNNING)
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

    citations = []
    for index in range(8):
        title = "广州AI实训基地怎么样" if index % 2 == 0 else f"普通页面 {index}"
        cit = MonitoringCitation(
            project_id=project.id, sample_id=sample.id,
            raw_url=f"https://example.com/{index}", normalized_url=f"https://example.com/{index}",
            domain="example.com", title=title, page_type=CitationPageType.ARTICLE, page_type_source="rule",
            source_category=SourceCategory.SOCIAL_COMMUNITY,
            review_status=CitationReviewStatus.MANUAL_CONFIRMED, is_brand_related=True,
        )
        db.add(cit)
        citations.append(cit)
    # 一条负面提示页，用于验证预排序
    negative = MonitoringCitation(
        project_id=project.id, sample_id=sample.id,
        raw_url="https://example.com/bad", normalized_url="https://example.com/bad",
        domain="example.com", title="这家机构是不是骗局？退款难、还我血汗钱",
        page_type=CitationPageType.ARTICLE, page_type_source="rule",
        source_category=SourceCategory.SOCIAL_COMMUNITY,
        review_status=CitationReviewStatus.MANUAL_CONFIRMED, is_brand_related=True,
    )
    db.add(negative)
    citations.append(negative)
    db.commit()
    return citations


def test_sampling_is_stable_and_presorted(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"ss-{suffix}")
    _seed(db, project)

    first = sampling_queue(db, project.id, round_no=1, size=4)
    second = sampling_queue(db, project.id, round_no=1, size=4)
    assert [item["citation_id"] for item in first["sample"]] == [item["citation_id"] for item in second["sample"]]
    assert first["scope"] == "brand_related"
    assert first["widened"] is False
    # 带负面提示的页要么被抽进样本，要么出现在风险预排序里，且一定带 hints
    assert any(item["hints"] for item in first["sample"] + first["risk_scan"])
    for item in first["risk_scan"]:
        assert item["hints"]
    # 预排序不影响抽样批本身包含哪些条目
    assert len(first["sample"]) == 4


def test_double_blind_and_consensus(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cf-{suffix}")
    editor = user_factory(f"cf-e-{suffix}")
    editor2 = user_factory(f"cf-e2-{suffix}")
    viewer = user_factory(f"cf-v-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, editor2, RoleCode.EDITOR)
    member_factory(project, viewer, RoleCode.VIEWER)
    citations = _seed(db, project)

    queue = client.get(
        f"/api/v1/projects/{project.id}/sentiment/sampling?round_no=2&size=3",
        headers=_auth(viewer),
    ).json()["data"]
    first_id = queue["sample"][0]["citation_id"]
    second_id = queue["sample"][1]["citation_id"]

    for user, polarity in ((editor, "positive"), (editor2, "positive"), (editor, "negative")):
        client.post(
            f"/api/v1/projects/{project.id}/sentiment/{first_id}/label",
            json={"polarity": polarity}, headers=_auth(user),
        )
    # 第二个样本只有一个人标：算单标注，不算双人共识
    client.post(
        f"/api/v1/projects/{project.id}/sentiment/{second_id}/label",
        json={"polarity": "negative"}, headers=_auth(editor),
    )

    # 同一人重复标同一引用：只留最后一条，不产生第二条
    again = client.post(
        f"/api/v1/projects/{project.id}/sentiment/{first_id}/label",
        json={"polarity": "neutral"}, headers=_auth(editor),
    ).json()["data"]
    assert again["polarity"] == "neutral"

    result = client.get(
        f"/api/v1/projects/{project.id}/sentiment/consensus?round_no=2&size=3",
        headers=_auth(viewer),
    ).json()["data"]
    assert result["sampled"] == 3
    # first 现在两人意见相左（neutral vs positive）→ disputed
    assert result["disputed"] == 1
    assert result["reportable"] is False
    assert result["positive_rate"] is None
    assert result["min_report"] == MIN_REPORT


def test_cumulative_consensus_unions_rounds(db, project_factory, user_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cc-{suffix}")
    citations = _seed(db, project)
    ordered_ids = sorted(str(citation.id) for citation in citations)

    def _fixed_rank(round_no, citation_id):
        offset = 0 if round_no == 1 else 2
        index = ordered_ids.index(str(citation_id))
        return f"{(index - offset) % len(ordered_ids):04d}"

    monkeypatch.setattr("app.services.sentiment_sampling._rank_key", _fixed_rank)
    rounds = {round_no: [item["citation_id"] for item in sampling_queue(db, project.id, round_no=round_no, size=2)["sample"]]
              for round_no in (1, 2)}
    union = set(rounds[1]) | set(rounds[2])
    assert len(union) == 4  # 固定排序后两轮各取 2 条且不重叠

    # 同一条引用两人同档，才进共识
    cit = next(iter(union))
    for actor in (user_factory(f"cc-a-{suffix}").id, user_factory(f"cc-b-{suffix}").id):
        db.add(SentimentLabel(project_id=project.id, citation_id=cit, polarity=SentimentPolarity.POSITIVE,
                              labeled_by=actor, labeled_at=datetime.now(UTC)))
    db.commit()

    cumulative = cumulative_consensus(db, project.id, size=2, max_rounds=2)
    assert cumulative["cumulative"] is True
    assert cumulative["sampled"] == len(union)
    assert cumulative["consensus_total"] == 1
    assert cumulative["counts"]["positive"] == 1
    assert cumulative["reportable"] is False


def test_consensus_requires_two_labels(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cs-{suffix}")
    _seed(db, project)
    result = consensus(db, project.id, round_no=3, size=3)
    assert result["consensus_total"] == 0
    assert result["unlabeled"] == 3
    assert result["positive_rate"] is None

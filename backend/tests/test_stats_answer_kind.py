"""统计层按 answer_kind 分组：answer / search_result 各自独立分母。"""

import uuid
from datetime import datetime, timezone

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    AnswerKind,
    EngineEntryType,
    QuestionStatus,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _seed_samples(db, project) -> None:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(
        code=f"eng-{suffix}",
        name="引擎",
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
        name="网页端",
        supports_search=True,
        is_active=True,
    )
    db.add(entry)
    db.flush()
    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="测试问题",
        question_type=QuestionType.GENERAL,
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
        text="测试正文",
    )
    db.add(version)
    db.flush()
    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="轮次-1",
        status=RoundStatus.RUNNING,
    )
    db.add(round_row)
    db.flush()

    # answer(提及) / search_result(未提及) / NULL(提及，按 answer 兜底)
    rows = [
        (1, AnswerKind.ANSWER, True),
        (2, AnswerKind.SEARCH_RESULT, False),
        (3, None, True),
    ]
    for sampling_no, kind, mentioned in rows:
        task = MonitoringTask(
            project_id=project.id,
            round_id=round_row.id,
            question_version_id=version.id,
            engine_entry_id=entry.id,
            sampling_no=sampling_no,
            sampling_mode=SamplingMode.SEARCH_ON,
            status=TaskStatus.DONE,
        )
        db.add(task)
        db.flush()
        db.add(
            MonitoringSample(
                project_id=project.id,
                task_id=task.id,
                attempt_no=1,
                status=SampleStatus.HIT,
                sampled_at=datetime.now(timezone.utc),
                answer_kind=kind,
                brand_mentioned=mentioned,
            )
        )
    db.flush()


def test_overview_by_answer_kind_keeps_two_scopes_separate(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"ak-stats-{suffix}")
    viewer = user_factory(f"ak-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    _seed_samples(db, project)
    db.commit()

    response = client.get(
        f"/api/v1/projects/{project.id}/stats/overview-by-answer-kind",
        headers=_auth(viewer),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [item["answer_kind"] for item in data] == ["answer", "search_result"]

    answer, search = data
    # NULL 视为 answer 兜底：answer 组 2 条有效、2 条提及
    assert answer["valid_answers"] == 2
    assert answer["brand_mentioned_answers"] == 2
    assert answer["brand_mention_rate"] == 1.0
    # 检索口径独立分母：只有 1 条、0 条提及，不被 answer 的提及率稀释
    assert search["valid_answers"] == 1
    assert search["brand_mentioned_answers"] == 0
    assert search["brand_mention_rate"] == 0.0

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


def _add_sample_for_type(db, project, question_type: QuestionType, *, sampling_no: int, mentioned: bool) -> None:
    suffix = uuid.uuid4().hex[:6]
    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title=f"{question_type.value} 问题",
        question_type=question_type,
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
    engine = AiEngine(code=f"e-{suffix}", name="引擎", vendor="测试", supports_search=True)
    db.add_all([version, engine])
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        name="网页端",
        entry_type=EngineEntryType.WEB_USER,
        is_active=True,
    )
    db.add(entry)
    db.flush()
    round_row = MonitoringRound(project_id=project.id, seq=_next_seq(db, project.id), name="分区轮次")
    db.add(round_row)
    db.flush()
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
    db.add(MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        status=SampleStatus.HIT,
        sampled_at=datetime.now(timezone.utc),
        answer_kind=AnswerKind.ANSWER,
        brand_mentioned=mentioned,
    ))


def _next_seq(db, project_id) -> int:
    from sqlalchemy import func, select
    current = db.scalar(select(func.max(MonitoringRound.seq)).where(MonitoringRound.project_id == project_id))
    return int(current or 0) + 1


def test_overview_defaults_to_general_and_question_type_filter(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"qt-stats-{suffix}")
    viewer = user_factory(f"qt-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    _add_sample_for_type(db, project, QuestionType.GENERAL, sampling_no=1, mentioned=True)
    _add_sample_for_type(db, project, QuestionType.BRAND, sampling_no=1, mentioned=False)
    db.flush()

    general = client.get(f"/api/v1/projects/{project.id}/stats/overview", headers=_auth(viewer))
    assert general.status_code == 200, general.text
    assert general.json()["data"]["valid_answers"] == 1

    all_types = client.get(
        f"/api/v1/projects/{project.id}/stats/overview",
        params={"question_type": "all"},
        headers=_auth(viewer),
    )
    assert all_types.status_code == 200, all_types.text
    assert all_types.json()["data"]["valid_answers"] == 2

    brand = client.get(
        f"/api/v1/projects/{project.id}/stats/overview",
        params={"question_type": "brand"},
        headers=_auth(viewer),
    )
    assert brand.status_code == 200, brand.text
    assert brand.json()["data"]["valid_answers"] == 1

    # 分引擎/分题目不传 question_type 时保留全量，不被总览默认值带走
    by_question = client.get(
        f"/api/v1/projects/{project.id}/stats/by-question",
        headers=_auth(viewer),
    )
    assert by_question.status_code == 200, by_question.text
    assert len(by_question.json()["data"]) == 2


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

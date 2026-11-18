"""A4：resample 与 reanalyze 语义拆分。

- resample：同一轮次新建 sampling_no 的逻辑样本（新 task + outbox），不是同任务重试；
- reanalyze：不请求引擎，用已留存答案按本轮快照重算，样本数与分母不变；
- 轮次已结束时拒绝 resample。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.errors import TaskRejectedError
from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    BrandProfile,
    MonitoringSample,
    MonitoringTask,
    OutboxEvent,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    EngineEntryType,
    QuestionStatus,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.measurement_snapshot import SNAPSHOT_VERSION
from app.services.monitoring_batch import create_round
from app.services.monitoring_collection import execute_task, reanalyze_sample, resample_sample
from app.services.monitoring_extraction import AnswerPayload


class FakeAdapter:
    def __init__(self, payload: AnswerPayload) -> None:
        self.payload = payload
        self.calls = 0

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        self.calls += 1
        return self.payload


def _make_question(db, project) -> tuple[Question, QuestionVersion]:
    question = Question(
        project_id=project.id,
        code=f"Q-{uuid.uuid4().hex[:6]}",
        title="广州基地在哪，怎么报名？",
        question_type=QuestionType.BRAND,
        status=QuestionStatus.ACTIVE,
        current_version_no=1,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text=question.title,
        question_type=QuestionType.BRAND,
    )
    db.add(version)
    db.flush()
    return question, version


def _make_engine(db) -> AiEngineEntry:
    engine = AiEngine(
        code=f"eng-{uuid.uuid4().hex[:6]}",
        name="测试引擎",
        vendor="测试",
        is_active=True,
    )
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        entry_type=EngineEntryType.WEB_USER,
        name=f"入口-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    db.add(entry)
    db.flush()
    return entry


def _make_task(db, project, round_row, version, entry, *, sampling_no=1) -> MonitoringTask:
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=sampling_no,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()
    return task


def _prepare_project(db, project_factory, user_factory, *, alias="旧别名"):
    project = project_factory(f"a4-{uuid.uuid4().hex[:6]}")
    actor = user_factory(f"a4-{uuid.uuid4().hex[:6]}")
    profile = BrandProfile(
        project_id=project.id,
        canonical_name="广东省AI数字人才就业实训基地",
        aliases=[alias],
        identifiers=[],
        owned_domains=[],
        is_active=True,
    )
    db.add(profile)
    db.flush()
    round_row = create_round(
        db,
        project_id=project.id,
        actor_id=actor.id,
        name="A4 轮次",
        is_baseline=False,
        planned_at=None,
    )
    question, version = _make_question(db, project)
    entry = _make_engine(db)
    return project, actor, profile, round_row, question, version, entry


def test_resample_creates_new_logical_sample(db, project_factory, user_factory):
    project, actor, _profile, round_row, _question, version, entry = _prepare_project(
        db, project_factory, user_factory
    )
    task = _make_task(db, project, round_row, version, entry)
    adapter = FakeAdapter(AnswerPayload(text="旧别名提供 AI 实训"))
    execute_task(db, project_id=project.id, task_id=task.id, adapter=adapter)
    sample = db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task.id))
    assert sample is not None

    result = resample_sample(
        db, project_id=project.id, sample_id=sample.id, actor_id=actor.id
    )
    new_task = db.get(MonitoringTask, uuid.UUID(result["task_id"]))
    assert new_task is not None
    assert new_task.round_id == task.round_id
    assert new_task.question_version_id == task.question_version_id
    assert new_task.engine_entry_id == task.engine_entry_id
    assert new_task.sampling_no == 2
    assert new_task.status == TaskStatus.PENDING
    assert result["sampling_no"] == 2
    assert result["outbox_topic"] == "monitoring.task.execute"

    event = db.scalar(
        select(OutboxEvent).where(
            OutboxEvent.project_id == project.id,
            OutboxEvent.topic == "monitoring.task.execute",
            OutboxEvent.payload["task_id"].astext == result["task_id"],
        )
    )
    assert event is not None

    # 原任务的采样序号不变，新样本是独立任务而不是同任务 attempt
    assert task.sampling_no == 1
    samples = db.scalars(
        select(MonitoringSample).where(MonitoringSample.task_id == new_task.id)
    ).all()
    assert samples == []


def test_resample_rejected_when_round_closed(db, project_factory, user_factory):
    project, actor, _profile, round_row, _question, version, entry = _prepare_project(
        db, project_factory, user_factory
    )
    task = _make_task(db, project, round_row, version, entry)
    execute_task(
        db, project_id=project.id, task_id=task.id,
        adapter=FakeAdapter(AnswerPayload(text="旧别名")),
    )
    sample = db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task.id))
    round_row.status = RoundStatus.CLOSED
    db.flush()

    with pytest.raises(TaskRejectedError):
        resample_sample(db, project_id=project.id, sample_id=sample.id, actor_id=actor.id)


def test_reanalyze_uses_snapshot_and_keeps_sample_count(db, project_factory, user_factory):
    project, _actor, profile, round_row, _question, version, entry = _prepare_project(
        db, project_factory, user_factory
    )
    assert round_row.analysis_config_snapshot["snapshot_version"] == SNAPSHOT_VERSION
    task = _make_task(db, project, round_row, version, entry)
    adapter = FakeAdapter(AnswerPayload(text="旧别名提供 AI 实训"))
    execute_task(db, project_id=project.id, task_id=task.id, adapter=adapter)
    sample = db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task.id))
    assert sample.status == SampleStatus.HIT
    assert sample.analysis_version == round_row.analysis_config_version

    # 轮次建完后改品牌配置：重分析仍按快照词表，不应变成 miss
    profile.aliases = ["新别名"]
    db.flush()
    sample_count_before = db.scalar(
        select(func.count())
        .select_from(MonitoringSample)
        .where(MonitoringSample.project_id == project.id)
    )

    result = reanalyze_sample(db, project_id=project.id, sample_id=sample.id)
    assert result["status"] == "hit"
    assert result["brand_mentioned"] is True
    assert adapter.calls == 1  # 重分析不调用引擎

    db.refresh(sample)
    assert sample.status == SampleStatus.HIT
    assert sample.analysis_version == round_row.analysis_config_version
    assert sample.analyzed_at is not None
    sample_count_after = db.scalar(
        select(func.count())
        .select_from(MonitoringSample)
        .where(MonitoringSample.project_id == project.id)
    )
    assert sample_count_after == sample_count_before == 1


def test_resample_and_reanalyze_api(
    client, db, project_factory, user_factory, member_factory
):
    project, actor, _profile, round_row, _question, version, entry = _prepare_project(
        db, project_factory, user_factory
    )
    member_factory(project, actor, RoleCode.EDITOR)
    headers = {
        "Authorization": (
            f"Bearer {create_access_token(actor.id, token_version=actor.token_version)}"
        )
    }
    task = _make_task(db, project, round_row, version, entry)
    execute_task(
        db, project_id=project.id, task_id=task.id,
        adapter=FakeAdapter(AnswerPayload(text="旧别名提供 AI 实训")),
    )
    sample = db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task.id))

    resampled = client.post(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}/resample",
        headers=headers,
    )
    assert resampled.status_code == 201, resampled.text
    assert resampled.json()["data"]["sampling_no"] == 2

    reanalyzed = client.post(
        f"/api/v1/projects/{project.id}/monitoring/samples/{sample.id}/reanalyze",
        headers=headers,
    )
    assert reanalyzed.status_code == 200, reanalyzed.text
    assert reanalyzed.json()["data"]["status"] == "hit"
    db.refresh(sample)
    assert sample.status == SampleStatus.HIT

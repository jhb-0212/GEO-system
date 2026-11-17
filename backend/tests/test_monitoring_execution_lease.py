"""执行租约、执行尝试与限流留痕：GEO-02 / GEO-05 的回归验收。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringExecutionAttempt,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    AttemptStatus,
    EngineEntryType,
    FailureCode,
    QuestionStatus,
    QuestionType,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.monitoring_collection import (
    RateLimitedFailure,
    execute_task,
    mark_task_failed,
    recover_expired_leases,
)
from app.services.monitoring_extraction import AnswerPayload


class FakeAdapter:
    def __init__(self, payload: AnswerPayload) -> None:
        self.payload = payload
        self.calls = 0

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        self.calls += 1
        return self.payload


class DenyLimiter:
    def allow(self, engine_code: str, *, now=None) -> bool:
        return False


def _payload() -> AnswerPayload:
    return AnswerPayload(
        text="推荐广州基地的课程",
        raw_response={"answer": "推荐广州基地的课程"},
        engine_model="fake",
    )


def _seed_task(db, project, *, engine_code: str = "doubao_websearch"):
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(
        code=engine_code if engine_code != "doubao_websearch" else f"websearch-{suffix}",
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
        question_type=QuestionType.BRAND,
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
        text="测试问题正文",
    )
    db.add(version)
    db.flush()
    round_row = MonitoringRound(
        project_id=project.id, seq=1, name="轮次-1", is_baseline=True, status=RoundStatus.RUNNING
    )
    db.add(round_row)
    db.flush()
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()
    return engine, entry, task


def test_execute_with_lease_records_attempt_and_clears_lease(db, project_factory):
    project = project_factory(f"广州基地-lease-{uuid.uuid4().hex[:6]}")
    _engine, _entry, task = _seed_task(db, project)
    db.commit()

    result = execute_task(
        db,
        project_id=project.id,
        task_id=task.id,
        adapter=FakeAdapter(_payload()),
        worker_id="worker-test:1",
    )
    db.commit()

    assert result["status"] in (SampleStatus.HIT.value, SampleStatus.MISS.value)
    task = db.get(MonitoringTask, task.id)
    assert task.status == TaskStatus.DONE
    assert task.lease_owner is None
    row = db.query(MonitoringExecutionAttempt).filter_by(task_id=task.id).one()
    assert row.status == AttemptStatus.SUCCEEDED
    assert row.finished_at is not None


def test_rate_limit_denied_creates_failed_sample_and_attempt(db, project_factory):
    project = project_factory(f"rate-{uuid.uuid4().hex[:6]}")
    _engine, _entry, task = _seed_task(db, project)
    db.commit()

    with pytest.raises(RateLimitedFailure):
        execute_task(
            db,
            project_id=project.id,
            task_id=task.id,
            adapter=FakeAdapter(_payload()),
            rate_limiter=DenyLimiter(),
            worker_id="worker-test:1",
        )

    mark_task_failed(
        db,
        project_id=project.id,
        task_id=task.id,
        failure_code=FailureCode.RATE_LIMITED,
        note="引擎超过每分钟调用上限",
    )
    db.commit()

    task = db.get(MonitoringTask, task.id)
    assert task.status == TaskStatus.FAILED
    sample = db.query(MonitoringSample).filter_by(task_id=task.id).one()
    assert sample.status == SampleStatus.FAILED
    assert sample.failure_code == FailureCode.RATE_LIMITED
    attempt = db.query(MonitoringExecutionAttempt).filter_by(task_id=task.id).one()
    assert attempt.status == AttemptStatus.RATE_LIMITED


def test_recover_expired_lease_marks_uncertain_when_dispatched(db, project_factory):
    project = project_factory(f"lease-exp-{uuid.uuid4().hex[:6]}")
    _engine, _entry, task = _seed_task(db, project)
    task.status = TaskStatus.RUNNING
    task.lease_owner = "dead-worker"
    task.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    sample = MonitoringSample(
        project_id=project.id, task_id=task.id, attempt_no=1, status=SampleStatus.RUNNING
    )
    attempt = MonitoringExecutionAttempt(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        worker_id="dead-worker",
        status=AttemptStatus.DISPATCHING,
        lease_expires_at=task.lease_expires_at,
    )
    db.add_all([sample, attempt])
    db.commit()

    stats = recover_expired_leases(db)
    assert stats == {"scanned": 1, "requeued": 0, "uncertain": 1}

    task = db.get(MonitoringTask, task.id)
    assert task.status == TaskStatus.UNCERTAIN
    assert task.lease_owner is None
    attempt = db.query(MonitoringExecutionAttempt).filter_by(task_id=task.id).one()
    assert attempt.status == AttemptStatus.UNCERTAIN


def test_recover_expired_lease_requeues_when_not_dispatched(db, project_factory):
    project = project_factory(f"lease-req-{uuid.uuid4().hex[:6]}")
    _engine, _entry, task = _seed_task(db, project)
    task.status = TaskStatus.RUNNING
    task.lease_owner = "dead-worker"
    task.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    sample = MonitoringSample(
        project_id=project.id, task_id=task.id, attempt_no=1, status=SampleStatus.RUNNING
    )
    attempt = MonitoringExecutionAttempt(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        worker_id="dead-worker",
        status=AttemptStatus.CLAIMED,
        lease_expires_at=task.lease_expires_at,
    )
    db.add_all([sample, attempt])
    db.commit()

    stats = recover_expired_leases(db)
    assert stats == {"scanned": 1, "requeued": 1, "uncertain": 0}
    task = db.get(MonitoringTask, task.id)
    assert task.status == TaskStatus.PENDING
    sample = db.query(MonitoringSample).filter_by(task_id=task.id).one()
    assert sample.status == SampleStatus.FAILED
    assert "重排" in (sample.failure_note or "")

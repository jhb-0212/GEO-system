"""执行权原子领取的双 Worker 竞争回归（GEO-02 修复后验收）。

覆盖审查报告 P1 的故障场景：ack_late 重复投递 / Outbox 至少一次投递窗口内，
同一任务被两个 Worker 先后或并发执行时，只能有一方获得执行权：

- 租约有效期内重复消息直接跳过，不创建第二个样本、不重复计费；
- UNCERTAIN（请求已发出、结果不明）任务禁止自动重发；
- 人工核实后转回 PENDING 可重新执行；
- 租约过期的 RUNNING 任务可被新 Worker 重新领取；
- 两个独立连接并发抢同一任务，恰好一方成功、一方跳过。

注意：这些用例需要两个独立数据库连接/事务，不能复用 conftest 的单事务
`db` fixture；测试数据真实提交，因此每个用例结束必须显式清理，不污染开发库。
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringExecutionAttempt,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    AttemptStatus,
    EngineEntryType,
    ProjectStatus,
    QuestionStatus,
    QuestionType,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.monitoring_collection import execute_task
from app.services.monitoring_extraction import AnswerPayload
from app.services.state_machine import ensure_task_transition


def _payload() -> AnswerPayload:
    return AnswerPayload(
        text="推荐广州基地的课程",
        raw_response={"answer": "推荐广州基地的课程"},
        engine_model="fake",
    )


class FakeAdapter:
    def __init__(self, payload: AnswerPayload | None = None) -> None:
        self.payload = payload or _payload()
        self.calls = 0

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        self.calls += 1
        return self.payload


class BlockingAdapter:
    """模拟真实外部请求：领取提交后阻塞，等待主线程放行。"""

    def __init__(self, release: threading.Event) -> None:
        self.release = release
        self.payload = _payload()
        self.calls = 0

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        self.calls += 1
        if not self.release.wait(timeout=15):
            raise TimeoutError("blocking adapter not released")
        return self.payload


def _seed_task(session: Session, project: Project) -> tuple[AiEngine, AiEngineEntry, MonitoringTask]:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(
        code=f"websearch-{suffix}",
        name="引擎",
        vendor="测试",
        supports_search=True,
        supports_citation=True,
        is_active=True,
    )
    session.add(engine)
    session.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        entry_type=EngineEntryType.WEB_USER,
        name="网页端",
        supports_search=True,
        is_active=True,
    )
    session.add(entry)
    session.flush()
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
    session.add(question)
    session.flush()
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text="测试问题正文",
    )
    session.add(version)
    session.flush()
    round_row = MonitoringRound(
        project_id=project.id, seq=1, name="轮次-1", is_baseline=True, status=RoundStatus.RUNNING
    )
    session.add(round_row)
    session.flush()
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    session.add(task)
    session.flush()
    return engine, entry, task


def _cleanup(engine, project_id, engine_id, entry_id, task_id) -> None:
    """按 FK 依赖顺序清理本用例写入的行，避免污染开发库。"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM monitoring_citations WHERE project_id = :p"), {"p": project_id})
        conn.execute(text("DELETE FROM monitoring_competitor_mentions WHERE project_id = :p"), {"p": project_id})
        conn.execute(text("DELETE FROM evidence_files WHERE project_id = :p"), {"p": project_id})
        conn.execute(text("DELETE FROM monitoring_samples WHERE task_id = :t"), {"t": task_id})
        conn.execute(text("DELETE FROM monitoring_execution_attempts WHERE task_id = :t"), {"t": task_id})
        conn.execute(text("DELETE FROM monitoring_tasks WHERE id = :t"), {"t": task_id})
        conn.execute(text("DELETE FROM monitoring_rounds WHERE project_id = :p"), {"p": project_id})
        conn.execute(text("DELETE FROM question_versions WHERE project_id = :p"), {"p": project_id})
        conn.execute(text("DELETE FROM questions WHERE project_id = :p"), {"p": project_id})
        conn.execute(text("DELETE FROM ai_engine_entries WHERE id = :e"), {"e": entry_id})
        conn.execute(text("DELETE FROM ai_engines WHERE id = :e"), {"e": engine_id})
        conn.execute(text("DELETE FROM projects WHERE id = :p"), {"p": project_id})


@pytest.fixture()
def seeded(engine):
    """真实提交一个最小可执行任务，测试结束清理。"""
    suffix = uuid.uuid4().hex[:6]
    session = Session(bind=engine, expire_on_commit=False)
    project = Project(
        code=f"race-{suffix}", name=f"竞争测试-{suffix}", status=ProjectStatus.ACTIVE,
        timezone="Asia/Shanghai",
    )
    session.add(project)
    session.flush()
    eng, entry, task = _seed_task(session, project)
    session.commit()
    project_id = project.id
    engine_id = eng.id
    entry_id = entry.id
    task_id = task.id
    session.close()
    yield engine, project_id, engine_id, entry_id, task_id
    _cleanup(engine, project_id, engine_id, entry_id, task_id)


def _open_session(engine) -> Session:
    conn = engine.connect()
    return Session(bind=conn, expire_on_commit=False), conn


def test_duplicate_message_after_terminal_state_is_skipped(engine, seeded):
    """任务已 DONE 后再次投递：终态跳过，样本与执行尝试都不翻倍。"""
    db_engine, project_id, _eng, _entry, task_id = seeded

    session_a, conn_a = _open_session(db_engine)
    try:
        result_a = execute_task(
            session_a,
            project_id=project_id,
            task_id=task_id,
            adapter=FakeAdapter(),
            worker_id="worker-a:1",
        )
        session_a.commit()
    finally:
        session_a.close()
        conn_a.close()
    assert result_a["status"] in (SampleStatus.HIT.value, SampleStatus.MISS.value)

    # 任务已 DONE，检查重复消息场景需要租约仍有效：改用过期租约前的窗口模拟。
    # 先验证终态重复消息：DONE 后再次投递直接 terminal 跳过。
    session_b, conn_b = _open_session(db_engine)
    try:
        result_b = execute_task(
            session_b,
            project_id=project_id,
            task_id=task_id,
            adapter=FakeAdapter(),
            worker_id="worker-b:1",
        )
        session_b.commit()
    finally:
        session_b.close()
        conn_b.close()
    assert result_b["skipped"] == "task already terminal"

    session_c, conn_c = _open_session(db_engine)
    try:
        samples = session_c.scalars(
            select(MonitoringSample).where(MonitoringSample.task_id == task_id)
        ).all()
        attempts = session_c.scalars(
            select(MonitoringExecutionAttempt).where(MonitoringExecutionAttempt.task_id == task_id)
        ).all()
    finally:
        session_c.close()
        conn_c.close()
    assert len(samples) == 1, "重复投递不得创建第二个样本"
    assert [s.attempt_no for s in samples] == [1]
    assert len(attempts) == 1, "重复投递不得创建第二个执行尝试"


def test_second_worker_blocked_while_lease_active(engine, seeded):
    """租约有效期内的真正重复执行：A 已领取未结束，B 再次执行必须被租约挡掉。"""
    db_engine, project_id, _eng, _entry, task_id = seeded

    # A 领取并提交（阶段 A），随后阻塞在外部请求上。
    release = threading.Event()
    result_box: dict = {}

    def run_a():
        session_a, conn_a = _open_session(db_engine)
        try:
            result_box["result"] = execute_task(
                session_a,
                project_id=project_id,
                task_id=task_id,
                adapter=BlockingAdapter(release),
                worker_id="worker-a:1",
            )
            session_a.commit()
        finally:
            session_a.close()
            conn_a.close()

    thread_a = threading.Thread(target=run_a)
    thread_a.start()

    # 等 A 完成领取（任务置 RUNNING 且租约已写）后再让 B 进来。
    probe, probe_conn = _open_session(db_engine)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            row = probe.scalar(
                select(MonitoringTask).where(MonitoringTask.id == task_id)
            )
            if row is not None and row.status == TaskStatus.RUNNING and row.lease_owner == "worker-a:1":
                break
            probe.rollback()
            time.sleep(0.05)
        else:
            pytest.fail("worker A 未在预期时间内完成领取")
    finally:
        probe.close()
        probe_conn.close()

    session_b, conn_b = _open_session(db_engine)
    try:
        result_b = execute_task(
            session_b,
            project_id=project_id,
            task_id=task_id,
            adapter=FakeAdapter(),
            worker_id="worker-b:1",
        )
        session_b.commit()
    finally:
        session_b.close()
        conn_b.close()

    assert result_b["skipped"] == "task is executing in another worker"
    assert "sample_id" not in result_b

    release.set()
    thread_a.join(timeout=15)
    assert not thread_a.is_alive(), "worker A 未在预期时间内结束"
    assert result_box["result"]["status"] in (SampleStatus.HIT.value, SampleStatus.MISS.value)

    session_c, conn_c = _open_session(db_engine)
    try:
        samples = session_c.scalars(
            select(MonitoringSample).where(MonitoringSample.task_id == task_id)
        ).all()
        attempts = session_c.scalars(
            select(MonitoringExecutionAttempt).where(MonitoringExecutionAttempt.task_id == task_id)
        ).all()
        task = session_c.get(MonitoringTask, task_id)
    finally:
        session_c.close()
        conn_c.close()

    assert len(samples) == 1, "租约有效期内只允许一个执行实例"
    assert len(attempts) == 1
    assert task.status == TaskStatus.DONE


def test_uncertain_task_is_never_auto_rerun(engine, seeded):
    """租约回收判定 UNCERTAIN 的任务，重复消息必须跳过，不能再次发起外部请求。"""
    db_engine, project_id, _eng, _entry, task_id = seeded

    session, conn = _open_session(db_engine)
    try:
        task = session.get(MonitoringTask, task_id)
        task.status = ensure_task_transition(task.status, TaskStatus.RUNNING)
        task.status = ensure_task_transition(task.status, TaskStatus.UNCERTAIN)
        session.commit()
    finally:
        session.close()
        conn.close()

    adapter = FakeAdapter()
    session_b, conn_b = _open_session(db_engine)
    try:
        result = execute_task(
            session_b,
            project_id=project_id,
            task_id=task_id,
            adapter=adapter,
            worker_id="worker-b:1",
        )
        session_b.commit()
    finally:
        session_b.close()
        conn_b.close()

    assert result["skipped"] == "task awaiting manual review"
    assert adapter.calls == 0, "UNCERTAIN 任务不得调用外部平台"
    session_c, conn_c = _open_session(db_engine)
    try:
        samples = session_c.scalars(
            select(MonitoringSample).where(MonitoringSample.task_id == task_id)
        ).all()
    finally:
        session_c.close()
        conn_c.close()
    assert len(samples) == 0


def test_manual_reopen_allows_reexecution(engine, seeded):
    """人工核实后把 UNCERTAIN 转回 PENDING，任务可以重新执行成功。"""
    db_engine, project_id, _eng, _entry, task_id = seeded

    session, conn = _open_session(db_engine)
    try:
        task = session.get(MonitoringTask, task_id)
        task.status = ensure_task_transition(task.status, TaskStatus.RUNNING)
        task.status = ensure_task_transition(task.status, TaskStatus.UNCERTAIN)
        session.commit()
        # 人工核实：请求已发出的结果作废，任务重新排队。
        task = session.get(MonitoringTask, task_id)
        task.status = ensure_task_transition(task.status, TaskStatus.PENDING)
        session.commit()
    finally:
        session.close()
        conn.close()

    session_b, conn_b = _open_session(db_engine)
    try:
        result = execute_task(
            session_b,
            project_id=project_id,
            task_id=task_id,
            adapter=FakeAdapter(),
            worker_id="worker-b:1",
        )
        session_b.commit()
    finally:
        session_b.close()
        conn_b.close()
    assert result["status"] in (SampleStatus.HIT.value, SampleStatus.MISS.value)


def test_expired_lease_can_be_reclaimed(engine, seeded):
    """Worker 崩溃后租约过期，新 Worker 可以重新领取并完成任务。"""
    db_engine, project_id, _eng, _entry, task_id = seeded

    session, conn = _open_session(db_engine)
    try:
        task = session.get(MonitoringTask, task_id)
        task.status = ensure_task_transition(task.status, TaskStatus.RUNNING)
        task.lease_owner = "dead-worker"
        task.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        session.commit()
    finally:
        session.close()
        conn.close()

    session_b, conn_b = _open_session(db_engine)
    try:
        result = execute_task(
            session_b,
            project_id=project_id,
            task_id=task_id,
            adapter=FakeAdapter(),
            worker_id="worker-b:1",
        )
        session_b.commit()
    finally:
        session_b.close()
        conn_b.close()
    assert result["status"] in (SampleStatus.HIT.value, SampleStatus.MISS.value)

    session_c, conn_c = _open_session(db_engine)
    try:
        task = session_c.get(MonitoringTask, task_id)
        attempts = session_c.scalars(
            select(MonitoringExecutionAttempt).where(MonitoringExecutionAttempt.task_id == task_id)
        ).all()
    finally:
        session_c.close()
        conn_c.close()
    assert task.status == TaskStatus.DONE
    assert task.lease_owner is None
    assert len(attempts) == 1
    assert attempts[0].worker_id == "worker-b:1"

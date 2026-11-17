"""Worker 监测任务映射与状态收口测试（不连真实 Redis/Celery broker）。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models.enums import FailureCode
from app.services.monitoring_collection import RateLimitedFailure, TransientCollectionFailure
from app import worker


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


def test_send_outbox_event_maps_topic(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        worker.celery_app,
        "send_task",
        lambda name, **kwargs: calls.update({"name": name, **kwargs}),
    )
    event = SimpleNamespace(
        id=uuid.uuid4(),
        topic="monitoring.task.execute",
        payload={"project_id": str(uuid.uuid4()), "task_id": str(uuid.uuid4())},
    )
    worker._send_outbox_event(event)
    assert calls["name"] == "geo.monitoring.execute"
    assert calls["task_id"] == f"outbox-{event.id}"
    assert calls["args"][0] == str(event.id)

    with pytest.raises(ValueError, match="no worker handler"):
        worker._send_outbox_event(SimpleNamespace(id=uuid.uuid4(), topic="other", payload={}))


def test_send_outbox_event_rejects_bad_payload(monkeypatch):
    monkeypatch.setattr(worker.celery_app, "send_task", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="missing task_id"):
        worker._send_outbox_event(
            SimpleNamespace(id=uuid.uuid4(), topic="monitoring.task.execute", payload={})
        )


def test_dispatch_outbox_commits(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)
    monkeypatch.setattr(worker, "dispatch_pending_events", lambda db, send: {"pending_count": 1})
    assert worker.dispatch_outbox.run() == {"pending_count": 1}
    assert session.commits == 1


def test_schedule_monitoring_commits(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)
    monkeypatch.setattr(worker, "schedule_active_rounds", lambda db: {"created_task_count": 1})
    assert worker.schedule_monitoring.run() == {"created_task_count": 1}
    assert session.commits == 1


def test_execute_monitoring_task_success(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)
    monkeypatch.setattr(worker, "EngineRateLimiter", lambda: object())
    monkeypatch.setattr(
        worker,
        "execute_task",
        lambda db, **kwargs: {"task_id": str(kwargs["task_id"]), "status": "hit"},
    )
    task_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    result = worker.execute_monitoring_task.run("event-1", task_id, project_id)
    assert result["event_id"] == "event-1"
    assert result["status"] == "hit"
    assert session.commits == 1
    assert session.closed == 1


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (RateLimitedFailure("too many"), "rate_limited"),
        (TransientCollectionFailure("timeout"), "timeout"),
    ],
)
def test_execute_monitoring_task_final_failure_marks_task(monkeypatch, exc, expected_code):
    session = FakeSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)
    monkeypatch.setattr(worker, "EngineRateLimiter", lambda: object())
    monkeypatch.setattr(worker, "execute_task", lambda db, **kwargs: (_ for _ in ()).throw(exc))
    monkeypatch.setattr(worker, "mark_task_failed", lambda db, **kwargs: None)
    # Celery 任务实例的 request 是上下文对象；直接改到重试耗尽状态
    monkeypatch.setattr(worker.execute_monitoring_task.request, "retries", 3)
    result = worker.execute_monitoring_task.run("event-1", str(uuid.uuid4()), str(uuid.uuid4()))
    assert result["status"] == "failed"
    assert result["failure_code"] == expected_code
    assert session.commits >= 1


def test_rate_limited_branch_commits_before_marking_failed(monkeypatch):
    """限流分支不能 rollback：否则 pending→running 被撤销，mark_task_failed 会撞状态机。"""
    session = FakeSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)
    monkeypatch.setattr(worker, "EngineRateLimiter", lambda: object())
    monkeypatch.setattr(
        worker,
        "execute_task",
        lambda db, **kwargs: (_ for _ in ()).throw(RateLimitedFailure("too many")),
    )
    monkeypatch.setattr(worker, "mark_task_failed", lambda db, **kwargs: None)
    result = worker.execute_monitoring_task.run("event-1", str(uuid.uuid4()), str(uuid.uuid4()))
    assert result["failure_code"] == "rate_limited"
    assert session.rollbacks == 0
    # 一次保住 running / 失败样本，一次落 failed
    assert session.commits == 2
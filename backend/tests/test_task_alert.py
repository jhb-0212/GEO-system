"""任务失败告警聚合测试：同一失败类只首报、不同类超阈值汇总、Redis 降级。"""

import pytest

from app import worker


class FakeRedis:
    """只实现聚合用到的命令，足够验证计数、首次快照与类去重。"""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.ttls: dict[str, int] = {}
        self.closed = False

    def incr(self, key: str) -> int:
        value = int(self.values.get(key, 0)) + 1  # type: ignore[arg-type]
        self.values[key] = value
        return value

    def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return True

    def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str) -> object:
        return self.values.get(key)

    def close(self) -> None:
        self.closed = True


class BrokenRedis(FakeRedis):
    def incr(self, key: str) -> int:
        raise RuntimeError("redis down")


@pytest.fixture
def alert_env(monkeypatch):
    posted: list[dict[str, object]] = []
    fake = FakeRedis()
    monkeypatch.setattr(worker, "_alert_redis_client", lambda: fake)
    monkeypatch.setattr(worker, "_send_alert", lambda payload, url: posted.append(payload))
    monkeypatch.setattr(worker.settings, "task_alert_webhook", "http://alert.test/hook")
    monkeypatch.setattr(worker.settings, "task_alert_max_per_window", 5)
    monkeypatch.setattr(worker.settings, "task_alert_window_seconds", 300)
    return posted, fake


def make_payload(
    index: int,
    *,
    task_name: str = "geo.selftest.fail",
    exception_type: str = "RuntimeError",
    project_id: str | None = None,
) -> dict[str, object]:
    return {
        "event": "task_failed",
        "task_id": f"task-{index}",
        "task_name": task_name,
        "project_id": project_id,
        "exception_type": exception_type,
        "exception": f"{exception_type}('boom')",
        "host": "test-host",
        "app_env": "test",
        "time": "2026-11-11T12:00:00+08:00",
    }


def test_same_failure_class_only_first_alert_is_sent(alert_env):
    posted, fake = alert_env
    for index in range(20):
        worker._notify_task_failure(make_payload(index))

    assert [item["event"] for item in posted] == ["task_failed"]
    assert posted[0]["task_id"] == "task-0"
    assert posted[0]["failure_class"] == "unscoped|geo.selftest.fail|RuntimeError"
    assert fake.closed is True


def test_first_five_distinct_classes_are_sent_individually(alert_env):
    posted, _ = alert_env
    for index in range(5):
        worker._notify_task_failure(make_payload(index, exception_type=f"Error{index}"))

    assert [item["event"] for item in posted] == ["task_failed"] * 5
    assert [item["task_id"] for item in posted] == [f"task-{index}" for index in range(5)]


def test_repeated_class_does_not_consume_distinct_quota(alert_env):
    posted, _ = alert_env
    for index in range(20):
        worker._notify_task_failure(make_payload(index))
    for offset in range(4):
        worker._notify_task_failure(
            make_payload(20 + offset, exception_type=f"NewError{offset}")
        )

    assert len(posted) == 5, "1 条同类首报 + 4 条新类，仍未超过 5 类"
    assert [item["task_id"] for item in posted] == ["task-0"] + [
        f"task-{20 + offset}" for offset in range(4)
    ]
    assert all(item["event"] == "task_failed" for item in posted)


def test_sixth_distinct_class_sends_one_summary_with_total_count(alert_env):
    posted, _ = alert_env
    for index in range(20):
        worker._notify_task_failure(make_payload(index))
    for offset in range(5):
        worker._notify_task_failure(
            make_payload(20 + offset, exception_type=f"NewError{offset}")
        )

    assert len(posted) == 6, "1 条同类首报 + 4 条不同类 + 第 6 类触发汇总"
    summary = posted[-1]
    assert summary["event"] == "task_alert_suppressed"
    assert summary["reason"] == "distinct_failure_classes_exceeded"
    assert summary["failed_count"] == 25
    assert summary["distinct_failures"] == 6
    assert summary["trigger_failure_class"] == "unscoped|geo.selftest.fail|NewError4"
    assert summary["first_failure"]["task_id"] == "task-0"
    assert summary["last_failure"]["task_id"] == "task-24"
    assert summary["aggregation"] == "project_id + task_name + exception_type"


def test_different_projects_are_not_merged(alert_env):
    posted, _ = alert_env
    for index in range(10):
        worker._notify_task_failure(make_payload(index, project_id="project-a"))
    for index in range(10):
        worker._notify_task_failure(make_payload(index, project_id="project-b"))

    assert len(posted) == 2, "跨项目同任务名/同异常类型必须分开首报"
    assert [item["project_id"] for item in posted] == ["project-a", "project-b"]
    assert [item["failure_class"] for item in posted] == [
        "project-a|geo.selftest.fail|RuntimeError",
        "project-b|geo.selftest.fail|RuntimeError",
    ]


def test_redis_failure_falls_back_to_per_task_alert(monkeypatch):
    posted: list[dict[str, object]] = []
    broken = BrokenRedis()
    monkeypatch.setattr(worker, "_alert_redis_client", lambda: broken)
    monkeypatch.setattr(worker, "_send_alert", lambda payload, url: posted.append(payload))
    monkeypatch.setattr(worker.settings, "task_alert_webhook", "http://alert.test/hook")

    for index in range(20):
        worker._notify_task_failure(make_payload(index))

    assert len(posted) == 20, "Redis 不可用时必须降级逐条发送，不能吞告警"
    assert all(item["event"] == "task_failed" for item in posted)
    assert broken.closed is True


def test_new_window_resets_distinct_quota(alert_env):
    """窗口序号变化后重新计数，不能把上一个窗口的失败类去重状态带过来。"""
    _ = alert_env
    for index in range(5):
        slot = worker._reserve_alert_slot(
            make_payload(index, exception_type=f"Error{index}"), now=1000.0
        )
        assert slot.send is True
        assert slot.is_summary is False

    sixth = worker._reserve_alert_slot(
        make_payload(5, exception_type="Error5"), now=1000.0
    )
    assert sixth.send is True
    assert sixth.is_summary is True
    assert sixth.total_count == 6
    assert sixth.distinct_count == 6

    next_window = worker._reserve_alert_slot(
        make_payload(0, exception_type="Error0"), now=1300.0
    )
    assert next_window.send is True, "新窗口第一条必须恢复逐类首报"
    assert next_window.is_summary is False
    assert next_window.total_count == 1
    assert next_window.distinct_count == 1


def test_no_webhook_does_not_touch_redis(monkeypatch):
    posted: list[dict[str, object]] = []
    fake = FakeRedis()
    monkeypatch.setattr(worker, "_alert_redis_client", lambda: fake)
    monkeypatch.setattr(worker, "_send_alert", lambda payload, url: posted.append(payload))
    monkeypatch.setattr(worker.settings, "task_alert_webhook", "")

    worker._notify_task_failure(make_payload(0))

    assert posted == []
    assert fake.values == {}

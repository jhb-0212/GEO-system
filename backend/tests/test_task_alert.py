"""任务失败告警限流测试：用假 Redis 验证逐条/汇总/降级三条路径。"""

import pytest

from app import worker


class FakeRedis:
    """只实现限流用到的四个命令，足够验证计数与首次失败快照。"""

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

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
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


def make_payload(index: int) -> dict[str, object]:
    return {
        "event": "task_failed",
        "task_id": f"task-{index}",
        "task_name": "geo.selftest.fail",
        "exception": "RuntimeError('boom')",
        "host": "test-host",
        "app_env": "test",
        "time": "2026-11-11T12:00:00+08:00",
    }


def test_first_five_alerts_are_sent_individually(alert_env):
    posted, fake = alert_env
    for index in range(3):
        worker._notify_task_failure(make_payload(index))

    assert [item["event"] for item in posted] == ["task_failed"] * 3
    assert [item["task_id"] for item in posted] == ["task-0", "task-1", "task-2"]
    assert fake.closed is True


def test_sixth_alert_is_single_summary_and_rest_are_suppressed(alert_env):
    posted, fake = alert_env
    for index in range(20):
        worker._notify_task_failure(make_payload(index))

    assert len(posted) == 6, "5 条逐条 + 1 条汇总，其余 14 条必须抑制"
    assert [item["event"] for item in posted[:5]] == ["task_failed"] * 5
    summary = posted[5]
    assert summary["event"] == "task_alert_suppressed"
    assert summary["reason"] == "rate_limited"
    assert summary["failed_count"] == 6
    assert summary["max_per_window"] == 5
    assert summary["window_seconds"] == 300
    assert summary["first_failure"]["task_id"] == "task-0"
    assert summary["last_failure"]["task_id"] == "task-5"
    assert fake.closed is True


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


def test_new_window_resets_quota(alert_env):
    """窗口序号变化后重新计数，不能把上一个窗口的抑制状态带过来。"""
    _, _ = alert_env
    payload = make_payload(0)
    decisions = [worker._reserve_alert_slot(payload, now=1000.0) for _ in range(6)]
    assert [item[1] for item in decisions] == [False] * 5 + [True]
    assert decisions[5][2] == 6

    next_window = worker._reserve_alert_slot(payload, now=1300.0)
    assert next_window[0] is True, "新窗口第一条必须恢复逐条发送"
    assert next_window[1] is False
    assert next_window[2] == 1


def test_no_webhook_does_not_touch_redis(monkeypatch):
    posted: list[dict[str, object]] = []
    fake = FakeRedis()
    monkeypatch.setattr(worker, "_alert_redis_client", lambda: fake)
    monkeypatch.setattr(worker, "_send_alert", lambda payload, url: posted.append(payload))
    monkeypatch.setattr(worker.settings, "task_alert_webhook", "")

    worker._notify_task_failure(make_payload(0))

    assert posted == []
    assert fake.values == {}

"""Celery 异步执行器入口：只负责任务投递与执行，任务状态与业务结果一律落库。

启动（Windows 必须用 solo 池）：
    celery -A app.worker.celery_app worker --pool=solo --loglevel=info
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import urllib.request
from datetime import datetime

import redis
from celery import Celery, signals

from app.core.config import settings
from app.core.logging import configure_logging

# 心跳键只在 Redis 里存"最近一次活着的时间"，任务状态与业务结果仍只落库。
HEARTBEAT_KEY_PREFIX = "geo:worker:heartbeat:"
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TTL_SECONDS = 90

# 任务失败告警限流：同一时间窗内先逐条发，超过阈值只发一条汇总。
# 键按“环境 + 时间窗序号”隔离，不同窗口自然失效，多个 worker 共享同一计数。
TASK_ALERT_KEY_PREFIX = "geo:task-alert:"

configure_logging()
logger = logging.getLogger("geo.worker")

celery_app = Celery(
    "geo",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_track_started=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 启动时 broker 没就绪就一直重试，避免容器编排里先起 worker 后起 redis 直接退出
    broker_connection_retry_on_startup=True,
    # 保留 Celery 自己的 logger 名字，但统一交给 root 的 JSON handler
    worker_hijack_root_logger=False,
    timezone="Asia/Shanghai",
    enable_utc=True,
    result_expires=3600,
)


@celery_app.task(name="geo.ping")
def ping() -> str:
    """联通性自检任务，用于验证 broker / worker / result backend 链路。"""
    return "pong"


@celery_app.task(name="geo.selftest.fail")
def selftest_fail() -> None:
    """告警链路自检：投递即失败，用于验证 task_failure → TASK_ALERT_WEBHOOK 通路。"""
    raise RuntimeError("geo.selftest.fail: 告警链路自检")


def _heartbeat_loop(key: str) -> None:
    """每 30 秒写一次带 TTL 的时间戳；Redis 不可用时不退出 worker，只丢一次心跳。"""
    client = redis.from_url(
        settings.redis_url, socket_connect_timeout=2, socket_timeout=2
    )
    try:
        while True:
            try:
                client.set(key, str(int(time.time())), ex=HEARTBEAT_TTL_SECONDS)
            except Exception:  # noqa: BLE001 - 心跳失败不能影响任务执行
                pass
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)
    finally:
        client.close()


def _alert_redis_client() -> redis.Redis:
    """限流专用连接：独立于心跳，短超时，Redis 不可用时调用方降级为逐条发送。"""
    return redis.from_url(
        settings.redis_url, socket_connect_timeout=2, socket_timeout=2
    )


def _load_first_failure(raw: object) -> dict[str, object] | None:
    if not raw:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001 - 聚合信息损坏不应阻断告警
        return None
    return parsed if isinstance(parsed, dict) else None


def _reserve_alert_slot(
    payload: dict[str, object], now: float | None = None
) -> tuple[bool, bool, int, dict[str, object] | None, int]:
    """占用当前时间窗的告警配额。

    返回 ``(是否发送, 是否为汇总, 当前失败数, 首次失败, 窗口序号)``。
    超过 ``task_alert_max_per_window`` 后：第 max+1 条发一条汇总，之后本窗口内全部抑制。
    Redis 不可用时降级为逐条发送，保证告警不会因限流组件故障被吞掉。
    """
    max_per_window = max(0, int(settings.task_alert_max_per_window))
    window_seconds = max(1, int(settings.task_alert_window_seconds))
    if max_per_window == 0:
        return True, False, 0, None, 0

    current = time.time() if now is None else now
    window_index = int(current // window_seconds)
    count_key = f"{TASK_ALERT_KEY_PREFIX}{settings.app_env}:{window_index}:count"
    first_key = f"{TASK_ALERT_KEY_PREFIX}{settings.app_env}:{window_index}:first"
    client: redis.Redis | None = None
    try:
        client = _alert_redis_client()
        count = int(client.incr(count_key))
        # 多存一个窗口，避免边界附近计数键提前消失；键本身带窗口序号，不会误用旧计数。
        client.expire(count_key, window_seconds * 2)
        if count == 1:
            client.set(
                first_key,
                json.dumps(payload, ensure_ascii=False),
                ex=window_seconds * 2,
            )
        if count <= max_per_window:
            return True, False, count, None, window_index
        if count == max_per_window + 1:
            return True, True, count, _load_first_failure(client.get(first_key)), window_index
        return False, True, count, None, window_index
    except Exception as exc:  # noqa: BLE001 - 限流组件故障不能阻断告警
        logger.warning(
            "task alert rate limit unavailable; fallback to per-task",
            extra={"fields": {"alert_error": str(exc)}},
        )
        return True, False, 0, None, window_index
    finally:
        if client is not None:
            client.close()


def _build_alert_summary(
    payload: dict[str, object],
    count: int,
    first_failure: dict[str, object] | None,
    window_index: int,
) -> dict[str, object]:
    window_seconds = max(1, int(settings.task_alert_window_seconds))
    max_per_window = max(0, int(settings.task_alert_max_per_window))
    window_start = (
        datetime.fromtimestamp(window_index * window_seconds)
        .astimezone()
        .isoformat(timespec="seconds")
    )
    return {
        "event": "task_alert_suppressed",
        "reason": "rate_limited",
        "window_seconds": window_seconds,
        "window_start": window_start,
        "max_per_window": max_per_window,
        "failed_count": count,
        "first_failure": first_failure,
        "last_failure": payload,
        "app_env": settings.app_env,
        "note": (
            f"同一 {window_seconds} 秒窗口内失败任务超过 {max_per_window} 条；"
            "前若干条已单独推送，本窗口后续失败不再逐条推送。"
            "完整任务列表见 worker 日志与任务记录。"
        ),
    }


def _send_alert(payload: dict[str, object], url: str) -> None:
    try:
        body = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(body, timeout=5) as response:  # noqa: S310 - 配置项由部署方给定
            response.read()
        logger.info(
            "task alert sent",
            extra={"fields": {"event": payload.get("event"), "task_id": payload.get("task_id")}},
        )
    except Exception as exc:  # noqa: BLE001 - 告警失败不能影响任务
        logger.warning(
            "task failure alert failed",
            extra={"fields": {**payload, "alert_error": str(exc)}},
        )


def _notify_task_failure(payload: dict[str, object]) -> None:
    """任务失败推送到 TASK_ALERT_WEBHOOK；先经 Redis 限流，超阈值只发一条汇总。"""
    url = settings.task_alert_webhook
    if not url:
        logger.warning("task failed without alert webhook", extra={"fields": payload})
        return

    send, is_summary, count, first_failure, window_index = _reserve_alert_slot(payload)
    if not send:
        logger.info(
            "task failure alert suppressed by rate limit",
            extra={
                "fields": {
                    "task_id": payload.get("task_id"),
                    "failed_count": count,
                    "window_seconds": settings.task_alert_window_seconds,
                }
            },
        )
        return
    if is_summary:
        payload = _build_alert_summary(payload, count, first_failure, window_index)
    _send_alert(payload, url)


@signals.task_failure.connect
def alert_task_failure(
    sender: object = None,
    task_id: str | None = None,
    exception: object = None,
    **kwargs: object,
) -> None:
    payload = {
        "event": "task_failed",
        "task_id": task_id,
        "task_name": getattr(sender, "name", None),
        "exception": repr(exception)[:500],
        "host": socket.gethostname(),
        "app_env": settings.app_env,
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _notify_task_failure(payload)


@signals.worker_ready.connect
def start_heartbeat(**kwargs: object) -> None:
    # Celery 在启动阶段会给自己挂 handler；ready 之后收回，统一走 root 的 JSON 格式
    configure_logging()
    for name in list(logging.root.manager.loggerDict):
        if name.startswith(("celery", "kombu")):
            target = logging.getLogger(name)
            target.handlers = []
            target.propagate = True
    logger.info("worker heartbeat started", extra={"fields": {"interval_s": HEARTBEAT_INTERVAL_SECONDS, "ttl_s": HEARTBEAT_TTL_SECONDS}})
    host = socket.gethostname()
    key = f"{HEARTBEAT_KEY_PREFIX}{host}:{os.getpid()}"
    threading.Thread(target=_heartbeat_loop, args=(key,), name="geo-heartbeat", daemon=True).start()

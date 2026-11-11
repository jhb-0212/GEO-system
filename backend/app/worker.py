"""Celery 异步执行器入口：只负责任务投递与执行，任务状态与业务结果一律落库。

启动（Windows 必须用 solo 池）：
    celery -A app.worker.celery_app worker --pool=solo --loglevel=info
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime

import redis
from celery import Celery, signals

from app.core.config import settings
from app.core.logging import configure_logging

# 心跳键只在 Redis 里存"最近一次活着的时间"，任务状态与业务结果仍只落库。
HEARTBEAT_KEY_PREFIX = "geo:worker:heartbeat:"
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TTL_SECONDS = 90

# 任务失败告警限流：按“项目 + 任务名 + 异常类型”聚合，同一类失败窗口内只首报一次；
# 不同失败类超过阈值只发一条汇总。键按“环境 + 时间窗序号”隔离，多个 worker 共享。
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


def _failure_class(payload: dict[str, object]) -> str:
    """告警聚合维度：项目 + 任务名 + 异常类型，不把会变的异常文本带进键。"""
    return "|".join(
        [
            str(payload.get("project_id") or "unscoped"),
            str(payload.get("task_name") or "unknown"),
            str(payload.get("exception_type") or "Unknown"),
        ]
    )


def _failure_fingerprint(failure_class: str) -> str:
    return hashlib.sha256(failure_class.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class AlertSlot:
    """一次窗口配额决策；计数与首次失败分开，便于汇总如实报总量。"""

    send: bool
    is_summary: bool
    total_count: int
    distinct_count: int
    first_failure: dict[str, object] | None
    window_index: int
    failure_class: str


def _reserve_alert_slot(
    payload: dict[str, object], now: float | None = None
) -> AlertSlot:
    """占用当前时间窗的告警配额。

    聚合键为 ``project_id + task_name + exception_type``：同一类失败在一个窗口内
    只首报一次；不同失败类累计超过 ``task_alert_max_per_window`` 时，第 max+1 类
    发一条汇总，之后本窗口内新的失败类不再逐类推送。``total_count`` 记录窗口内
    失败任务总数，``distinct_count`` 记录失败类数。Redis 不可用时降级为逐条发送。
    """
    max_per_window = max(0, int(settings.task_alert_max_per_window))
    window_seconds = max(1, int(settings.task_alert_window_seconds))
    failure_class = _failure_class(payload)
    if max_per_window == 0:
        return AlertSlot(True, False, 0, 0, None, 0, failure_class)

    current = time.time() if now is None else now
    window_index = int(current // window_seconds)
    base = f"{TASK_ALERT_KEY_PREFIX}{settings.app_env}:{window_index}"
    total_key = f"{base}:total"
    first_key = f"{base}:first"
    distinct_key = f"{base}:distinct"
    class_key = f"{base}:class:{_failure_fingerprint(failure_class)}"
    client: redis.Redis | None = None
    try:
        client = _alert_redis_client()
        total = int(client.incr(total_key))
        client.expire(total_key, window_seconds * 2)
        if total == 1:
            client.set(
                first_key,
                json.dumps(payload, ensure_ascii=False),
                ex=window_seconds * 2,
            )

        # SET NX 成功 = 本窗口第一次见到这个失败类；失败类计数只在首次出现时 +1。
        first_of_class = bool(
            client.set(class_key, "1", nx=True, ex=window_seconds * 2)
        )
        if not first_of_class:
            current_distinct = int(client.get(distinct_key) or 0)
            return AlertSlot(
                False, False, total, current_distinct, None, window_index, failure_class
            )

        distinct = int(client.incr(distinct_key))
        client.expire(distinct_key, window_seconds * 2)
        if distinct <= max_per_window:
            return AlertSlot(True, False, total, distinct, None, window_index, failure_class)
        if distinct == max_per_window + 1:
            return AlertSlot(
                True,
                True,
                total,
                distinct,
                _load_first_failure(client.get(first_key)),
                window_index,
                failure_class,
            )
        return AlertSlot(False, False, total, distinct, None, window_index, failure_class)
    except Exception as exc:  # noqa: BLE001 - 限流组件故障不能阻断告警
        logger.warning(
            "task alert aggregation unavailable; fallback to per-task",
            extra={"fields": {"alert_error": str(exc)}},
        )
        return AlertSlot(True, False, 0, 0, None, window_index, failure_class)
    finally:
        if client is not None:
            client.close()


def _build_alert_summary(
    slot: AlertSlot,
    payload: dict[str, object],
) -> dict[str, object]:
    window_seconds = max(1, int(settings.task_alert_window_seconds))
    max_per_window = max(0, int(settings.task_alert_max_per_window))
    window_start = (
        datetime.fromtimestamp(slot.window_index * window_seconds)
        .astimezone()
        .isoformat(timespec="seconds")
    )
    return {
        "event": "task_alert_suppressed",
        "reason": "distinct_failure_classes_exceeded",
        "window_seconds": window_seconds,
        "window_start": window_start,
        "max_per_window": max_per_window,
        "failed_count": slot.total_count,
        "distinct_failures": slot.distinct_count,
        "trigger_failure_class": slot.failure_class,
        "first_failure": slot.first_failure,
        "last_failure": payload,
        "app_env": settings.app_env,
        "aggregation": "project_id + task_name + exception_type",
        "note": (
            f"同一 {window_seconds} 秒窗口内不同失败类超过 {max_per_window} 类；"
            "同一类失败只首报一次，后续同类失败不再逐条推送。"
            "failed_count 为本窗口失败任务总数，distinct_failures 为失败类数；"
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
    """任务失败推送到 TASK_ALERT_WEBHOOK；先按失败类聚合，超阈值只发一条汇总。"""
    url = settings.task_alert_webhook
    if not url:
        logger.warning("task failed without alert webhook", extra={"fields": payload})
        return

    payload.setdefault("failure_class", _failure_class(payload))
    slot = _reserve_alert_slot(payload)
    if not slot.send:
        logger.info(
            "task failure alert suppressed by aggregation",
            extra={
                "fields": {
                    "task_id": payload.get("task_id"),
                    "failure_class": slot.failure_class,
                    "failed_count": slot.total_count,
                    "distinct_failures": slot.distinct_count,
                    "window_seconds": settings.task_alert_window_seconds,
                }
            },
        )
        return
    if slot.is_summary:
        payload = _build_alert_summary(slot, payload)
    _send_alert(payload, url)


def _extract_project_id(
    args: tuple[object, ...] | None, kwargs: dict[str, object] | None
) -> str | None:
    """从 Celery 任务的 kwargs / 首个 dict 参数里取 project_id；取不到返回 None。

    不查库：告警链路本身不应因数据库不可用而失败。取不到项目时归入 unscoped，
    仍按任务名与异常类型聚合。
    """
    if kwargs:
        value = kwargs.get("project_id")
        if value:
            return str(value)
    for arg in args or ():
        if isinstance(arg, dict):
            value = arg.get("project_id")
            if value:
                return str(value)
    return None


@signals.task_failure.connect
def alert_task_failure(
    sender: object = None,
    task_id: str | None = None,
    exception: object = None,
    args: tuple[object, ...] | None = None,
    kwargs: dict[str, object] | None = None,
    **extra: object,
) -> None:
    project_id = _extract_project_id(args, kwargs)
    exception_type = type(exception).__name__ if exception is not None else "Unknown"
    payload = {
        "event": "task_failed",
        "task_id": task_id,
        "task_name": getattr(sender, "name", None),
        "project_id": project_id,
        "exception_type": exception_type,
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

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


def _notify_task_failure(payload: dict[str, object]) -> None:
    """任务失败推送到 TASK_ALERT_WEBHOOK；未配置或推送失败都只记日志，不影响 worker。"""
    url = settings.task_alert_webhook
    if not url:
        logger.warning("task failed without alert webhook", extra={"fields": payload})
        return
    try:
        body = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(body, timeout=5) as response:  # noqa: S310 - 配置项由部署方给定
            response.read()
        logger.info("task failure alert sent", extra={"fields": payload})
    except Exception as exc:  # noqa: BLE001 - 告警失败不能影响任务
        logger.warning(
            "task failure alert failed",
            extra={"fields": {**payload, "alert_error": str(exc)}},
        )


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

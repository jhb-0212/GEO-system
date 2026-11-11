"""Celery 异步执行器入口：只负责任务投递与执行，任务状态与业务结果一律落库。

启动（Windows 必须用 solo 池）：
    celery -A app.worker.celery_app worker --pool=solo --loglevel=info
"""

from __future__ import annotations

import os
import socket
import threading
import time

import redis
from celery import Celery, signals

from app.core.config import settings

# 心跳键只在 Redis 里存"最近一次活着的时间"，任务状态与业务结果仍只落库。
HEARTBEAT_KEY_PREFIX = "geo:worker:heartbeat:"
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TTL_SECONDS = 90

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
    timezone="Asia/Shanghai",
    enable_utc=True,
    result_expires=3600,
)


@celery_app.task(name="geo.ping")
def ping() -> str:
    """联通性自检任务，用于验证 broker / worker / result backend 链路。"""
    return "pong"


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


@signals.worker_ready.connect
def start_heartbeat(**kwargs: object) -> None:
    host = socket.gethostname()
    key = f"{HEARTBEAT_KEY_PREFIX}{host}:{os.getpid()}"
    threading.Thread(target=_heartbeat_loop, args=(key,), name="geo-heartbeat", daemon=True).start()

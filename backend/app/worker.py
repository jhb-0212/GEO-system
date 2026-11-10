"""Celery 异步执行器入口：只负责任务投递与执行，任务状态与业务结果一律落库。

启动（Windows 必须用 solo 池）：
    celery -A app.worker.celery_app worker --pool=solo --loglevel=info
"""

from celery import Celery

from app.core.config import settings

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
    timezone="Asia/Shanghai",
    enable_utc=True,
    result_expires=3600,
)


@celery_app.task(name="geo.ping")
def ping() -> str:
    """联通性自检任务，用于验证 broker / worker / result backend 链路。"""
    return "pong"

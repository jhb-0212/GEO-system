"""健康检查：验证 API、数据库、Redis 三层连通性，用于环境联调与部署探活。"""

import time

import redis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.responses import (
    HealthData,
    HealthDbData,
    HealthQueueData,
    HealthRedisData,
    HealthWorkerData,
)
from app.core.config import settings
from app.db.session import get_db
from app.worker import HEARTBEAT_KEY_PREFIX, HEARTBEAT_TTL_SECONDS

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthData)
def health() -> dict:
    return {"status": "ok", "service": "geo-api", "env": settings.app_env}


@router.get("/health/db", response_model=HealthDbData)
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 健康检查需要把原因透出
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unavailable", "detail": str(exc)},
        )
    return {"status": "ok", "database": "ok"}


@router.get("/health/redis", response_model=HealthRedisData)
def health_redis():
    client = redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"status": "error", "redis": "unavailable", "detail": str(exc)},
        )
    finally:
        client.close()
    return {"status": "ok", "redis": "ok"}


@router.get("/health/queue", response_model=HealthQueueData)
def health_queue():
    """读 broker 里默认队列的待消费条数；超过阈值返回 503，让监警系统能直接探到积压。"""
    queue_name = settings.celery_default_queue
    threshold = settings.queue_backlog_threshold
    client = redis.from_url(
        settings.celery_broker_url, socket_connect_timeout=2, socket_timeout=2
    )
    try:
        depth = int(client.llen(queue_name))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "queue": queue_name,
                "depth": -1,
                "threshold": threshold,
                "detail": str(exc),
            },
        )
    finally:
        client.close()

    if depth > threshold:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "queue": queue_name,
                "depth": depth,
                "threshold": threshold,
                "detail": f"队列积压 {depth} 条，超过阈值 {threshold}",
            },
        )
    return {
        "status": "ok",
        "queue": queue_name,
        "depth": depth,
        "threshold": threshold,
    }


@router.get("/health/worker", response_model=HealthWorkerData)
def health_worker():
    """读 worker 写的心跳键：没有键或全部超时返回 503，避免"队列有人消费"变成默认假设。"""
    client = redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    stale_after = HEARTBEAT_TTL_SECONDS + 30
    try:
        keys = list(client.scan_iter(match=f"{HEARTBEAT_KEY_PREFIX}*", count=100))
        workers = []
        now = int(time.time())
        for raw_key in keys:
            name = raw_key.decode("utf-8").removeprefix(HEARTBEAT_KEY_PREFIX)
            raw_value = client.get(raw_key)
            age = now - int(raw_value) if raw_value else stale_after + 1
            workers.append(
                {
                    "name": name,
                    "last_seen_seconds": max(age, 0),
                    "healthy": age <= stale_after,
                }
            )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"status": "error", "worker": "unavailable", "detail": str(exc)},
        )
    finally:
        client.close()

    if not workers:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "worker": "none",
                "stale_after_seconds": stale_after,
                "workers": [],
                "detail": "没有 worker 心跳键：worker 未启动或未连上 Redis",
            },
        )
    if not any(item["healthy"] for item in workers):
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "worker": "stale",
                "stale_after_seconds": stale_after,
                "workers": workers,
                "detail": "所有 worker 心跳均已超时",
            },
        )
    return {
        "status": "ok",
        "worker": "ok",
        "stale_after_seconds": stale_after,
        "workers": workers,
    }

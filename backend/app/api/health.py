"""健康检查：验证 API、数据库、Redis 三层连通性，用于环境联调与部署探活。"""

import redis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "geo-api", "env": settings.app_env}


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 健康检查需要把原因透出
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unavailable", "detail": str(exc)},
        )
    return {"status": "ok", "database": "ok"}


@router.get("/health/redis")
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

"""探活接口不鉴权：失败原因只进日志，响应不回显基础设施细节。"""

import json

import redis

from app.api import health as health_module
from app.api.health import health_db, health_redis


class _BrokenSession:
    def execute(self, *args, **kwargs):
        raise RuntimeError("postgresql://geo:secret@db.internal:5432/app")


def test_health_db_hides_infrastructure_detail():
    response = health_db(db=_BrokenSession())
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["detail"] == "数据库连接失败"
    assert "secret" not in response.body.decode()
    assert "db.internal" not in response.body.decode()


def test_health_redis_hides_infrastructure_detail(monkeypatch):
    def boom(*args, **kwargs):
        raise redis.RedisError("redis://:secret@cache.internal:6379/0")

    monkeypatch.setattr(health_module.redis, "from_url", boom)
    response = health_redis()
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["detail"] == "Redis 连接失败"
    assert "secret" not in response.body.decode()
    assert "cache.internal" not in response.body.decode()

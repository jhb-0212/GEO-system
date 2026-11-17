"""登录失败限流：同一账号 / 同一来源 IP 的分钟与小时窗口计数，防在线撞库。

设计取舍：
- 只统计失败尝试，成功登录清零；阈值来自 settings，便于按环境调整；
- 账号与 IP 各算一组计数，只伪造 IP 或只换账号都绕不过另一维；
- Redis 故障时放行并告警（与采集限流一致）：不因为限流组件不可用把所有人挡在门外；
- Redis 键里只存 sha256 摘要，不落明文账号 / IP。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

import redis

from app.core.config import settings

logger = logging.getLogger("geo.auth")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class LoginThrottle:
    def __init__(self, client: redis.Redis | None = None) -> None:
        self._client = client

    def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    def _keys(self, username: str, client_ip: str, moment: datetime) -> list[str]:
        username_key = _digest(username.strip().casefold())
        ip_key = _digest(client_ip or "unknown")
        minute_bucket = int(moment.timestamp() // 60)
        hour_bucket = moment.strftime("%Y%m%d%H")
        return [
            f"geo:auth:login:min:u:{username_key}:{minute_bucket}",
            f"geo:auth:login:min:ip:{ip_key}:{minute_bucket}",
            f"geo:auth:login:hour:u:{username_key}:{hour_bucket}",
            f"geo:auth:login:hour:ip:{ip_key}:{hour_bucket}",
        ]

    def _ips_key(self, username: str) -> str:
        """记录该账号最近失败来源 IP 的摘要集合。

        管理员解封时通常不知道用户 IP，只凭账号名无法清掉 IP 维度桶；
        这里只存 sha256 摘要，不落明文 IP。
        """
        return f"geo:auth:login:ips:{_digest(username.strip().casefold())}"

    def check(
        self,
        username: str,
        client_ip: str,
        *,
        now: datetime | None = None,
    ) -> int:
        """返回 0 表示放行；大于 0 表示当前窗口还需等待的秒数。"""
        moment = now or datetime.now(timezone.utc)
        minute_limit = max(1, int(settings.login_rate_limit_per_minute))
        hour_limit = max(1, int(settings.login_rate_limit_per_hour))
        try:
            client = self._redis()
            keys = self._keys(username, client_ip, moment)
            minute_used = max(int(client.get(key) or 0) for key in keys[:2])
            hour_used = max(int(client.get(key) or 0) for key in keys[2:])
        except redis.RedisError:
            logger.warning("login throttle unavailable; allow request")
            return 0
        if minute_used >= minute_limit:
            return 60 - moment.second
        if hour_used >= hour_limit:
            return 3600 - (moment.minute * 60 + moment.second)
        return 0

    def register_failure(
        self,
        username: str,
        client_ip: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """记录一次失败；返回 True 表示本次刚好触达阈值（用于只写一次锁定审计）。"""
        moment = now or datetime.now(timezone.utc)
        minute_limit = max(1, int(settings.login_rate_limit_per_minute))
        hour_limit = max(1, int(settings.login_rate_limit_per_hour))
        try:
            client = self._redis()
            locked = False
            ips_key = self._ips_key(username)
            for key in self._keys(username, client_ip, moment):
                count = int(client.incr(key))
                if count == 1:
                    client.expire(key, 7200)
                if key.startswith("geo:auth:login:min:") and count == minute_limit:
                    locked = True
                if key.startswith("geo:auth:login:hour:") and count == hour_limit:
                    locked = True
            client.sadd(ips_key, _digest(client_ip or "unknown"))
            client.expire(ips_key, 7200)
            return locked
        except redis.RedisError:
            logger.warning("login throttle unavailable; skip failure counter")
            return False

    def reset(self, username: str, client_ip: str, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(timezone.utc)
        try:
            self._redis().delete(*self._keys(username, client_ip, moment))
        except redis.RedisError:
            logger.warning("login throttle unavailable; skip reset")

    def reset_username(self, username: str, *, now: datetime | None = None) -> int:
        """只凭账号名解封：清该账号的窗口桶，以及它最近失败来源 IP 的窗口桶。

        返回清掉的键数量，便于审计与排障时确认真的动到了数据。
        """
        moment = now or datetime.now(timezone.utc)
        try:
            client = self._redis()
            username_key = _digest(username.strip().casefold())
            minute_bucket = int(moment.timestamp() // 60)
            hour_bucket = moment.strftime("%Y%m%d%H")
            ips_key = self._ips_key(username)
            ip_digests = client.smembers(ips_key)
            keys = [
                f"geo:auth:login:min:u:{username_key}:{minute_bucket}",
                f"geo:auth:login:hour:u:{username_key}:{hour_bucket}",
            ]
            for ip_digest in ip_digests:
                keys.append(f"geo:auth:login:min:ip:{ip_digest}:{minute_bucket}")
                keys.append(f"geo:auth:login:hour:ip:{ip_digest}:{hour_bucket}")
            client.delete(*keys)
            client.delete(ips_key)
            return len(keys)
        except redis.RedisError:
            logger.warning("login throttle unavailable; skip reset")
            return 0

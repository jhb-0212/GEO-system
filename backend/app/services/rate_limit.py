"""跨进程限流辅助：Redis 优先，Redis 不可用时退回进程内兜底。

不是通用限流框架，只服务两个明确场景：
- 发布可见性检测按项目 60 秒只允许触发一次；
- 发布可见性上游调用按全局最小间隔串行（避免多 worker 一起打爆 QPS）。

Redis 故障时退回进程内状态：单进程仍然有保护，多进程会退化为各自限速。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from math import ceil

import redis

from app.core.config import settings

logger = logging.getLogger("geo.rate_limit")


class ProjectCooldown:
    def __init__(
        self,
        *,
        namespace: str,
        seconds: float,
        client: redis.Redis | None = None,
    ) -> None:
        self._namespace = namespace
        self._seconds = seconds
        self._client = client
        self._memory: dict[uuid.UUID, float] = {}
        self._lock = threading.Lock()

    def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    def acquire(self, project_id: uuid.UUID) -> int:
        """返回 0 表示拿到租约；大于 0 表示还需等待的秒数。"""
        key = f"geo:{self._namespace}:{project_id}"
        try:
            acquired = self._redis().set(
                key,
                "1",
                nx=True,
                ex=max(1, ceil(self._seconds)),
            )
            if acquired:
                return 0
            ttl = int(self._redis().ttl(key))
            return max(1, ttl)
        except redis.RedisError:
            logger.warning("%s cooldown unavailable; use process fallback", self._namespace)
        now = time.monotonic()
        with self._lock:
            last = self._memory.get(project_id)
            if last is not None and now - last < self._seconds:
                return max(1, int(self._seconds - (now - last)) + 1)
            self._memory[project_id] = now
            return 0

    def release(self, project_id: uuid.UUID) -> None:
        """业务失败时释放租约，避免用户白等一个窗口。"""
        key = f"geo:{self._namespace}:{project_id}"
        try:
            self._redis().delete(key)
        except redis.RedisError:
            logger.warning("%s cooldown unavailable; skip release", self._namespace)
        with self._lock:
            self._memory.pop(project_id, None)


class GlobalIntervalLimiter:
    """跨进程最小调用间隔；Redis 不可用时退回进程锁。"""

    def __init__(
        self,
        *,
        namespace: str,
        interval_seconds: float,
        client: redis.Redis | None = None,
    ) -> None:
        self._namespace = namespace
        self._interval = max(0.0, interval_seconds)
        self._client = client
        self._lock = threading.Lock()
        self._last_call_at = 0.0

    def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    def wait(self, interval_seconds: float | None = None) -> None:
        interval = self._interval if interval_seconds is None else max(0.0, interval_seconds)
        if interval <= 0:
            return
        key = f"geo:{self._namespace}:qps"
        milliseconds = max(1, ceil(interval * 1000))
        try:
            client = self._redis()
            while True:
                if client.set(key, "1", nx=True, px=milliseconds):
                    return
                ttl_ms = int(client.pttl(key))
                if ttl_ms < 0:
                    # 键刚好过期但 SET NX 抢输；下一轮重试即可。
                    time.sleep(min(interval, 0.05))
                    continue
                time.sleep(min(interval, ttl_ms / 1000.0))
        except redis.RedisError:
            logger.warning("%s interval limiter unavailable; use process fallback", self._namespace)
        with self._lock:
            wait = self._last_call_at + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call_at = time.monotonic()


class IpWindowLimiter:
    """按来源 IP 的分钟窗口限流，服务于无需登录的公开接口。

    Redis 故障时放行：公开只读数据宁可少挡，也不能把正常访客挡在门外；
    与登录限流同一取舍，故障时打告警日志留痕。
    """

    def __init__(
        self,
        *,
        namespace: str,
        per_minute: int,
        client: redis.Redis | None = None,
    ) -> None:
        self._namespace = namespace
        self._per_minute = int(per_minute)
        self._client = client

    def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    @property
    def per_minute(self) -> int:
        """当前额度。

        公开接口的实例是模块级的，运行期若改了配置，调用方在请求入口把最新值写回即可
        生效，不必重启进程。
        """
        return self._per_minute

    @per_minute.setter
    def per_minute(self, value: int) -> None:
        self._per_minute = int(value)

    def consume(self, source_ip: str) -> bool:
        """True=允许本次请求；False=超出该 IP 在当前分钟窗口的额度。"""
        if self._per_minute <= 0:
            return True
        minute = int(time.time() // 60)
        key = f"geo:{self._namespace}:{source_ip}:{minute}"
        try:
            # 一次往返完成「计数 + 设过期」：EXPIRE NX 只在 key 还没有过期时间时设置，
            # 保证窗口固定 90 秒；若每次都 expire，高频下过期时间被不断后推，计数永不清零。
            pipe = self._redis().pipeline()
            pipe.incr(key)
            pipe.expire(key, 90, nx=True)
            count = int(pipe.execute()[0])
            return count <= self._per_minute
        except redis.RedisError:
            logger.warning("%s ip limiter unavailable; allow request", self._namespace)
            return True

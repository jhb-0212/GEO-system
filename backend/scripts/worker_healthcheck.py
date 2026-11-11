"""Worker 容器健康检查：读 Redis 心跳键，任一 worker 心跳在阈值内即返回 0。

用于 deploy/docker-compose.prod.yml 的 worker healthcheck；与 /health/worker 同一判据。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# 直接以脚本方式运行（python scripts/worker_healthcheck.py）时，sys.path[0] 是 scripts/，
# 需要把 backend/ 加进来，否则容器里同样会报 No module named 'app'。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis  # noqa: E402

from app.core.config import settings
from app.worker import HEARTBEAT_KEY_PREFIX, HEARTBEAT_TTL_SECONDS

STALE_AFTER_SECONDS = HEARTBEAT_TTL_SECONDS + 30


def main() -> int:
    client = redis.from_url(
        settings.redis_url, socket_connect_timeout=2, socket_timeout=2
    )
    try:
        now = int(time.time())
        ages = []
        for raw_key in client.scan_iter(match=f"{HEARTBEAT_KEY_PREFIX}*", count=100):
            raw_value = client.get(raw_key)
            ages.append(now - int(raw_value) if raw_value else STALE_AFTER_SECONDS + 1)
    except Exception as exc:  # noqa: BLE001
        print(f"worker heartbeat check failed: {exc}")
        return 1
    finally:
        client.close()

    fresh = [age for age in ages if age <= STALE_AFTER_SECONDS]
    if not fresh:
        print(
            f"no fresh worker heartbeat (keys={len(ages)}, "
            f"stale_after={STALE_AFTER_SECONDS}s)"
        )
        return 1
    print(f"worker heartbeat ok (fresh={len(fresh)}, stale_after={STALE_AFTER_SECONDS}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

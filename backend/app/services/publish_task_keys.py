"""发布任务幂等键：账号 + 渠道 + 内容版本 + 业务任务键 四元组哈希。

为什么单独成模块：手工建单与批次投喂是两条入口，但幂等键必须是同一份算法，
否则同一组四元组在两条入口下算出不同 key，就会出现「看着像重复、系统当成新任务」。
"""

import hashlib
import uuid


def idempotency_key(
    account_id: uuid.UUID,
    channel_id: uuid.UUID,
    version_id: uuid.UUID,
    task_key: str,
) -> str:
    raw = f"{account_id}:{channel_id}:{version_id}:{task_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

"""内容哈希：正文的 sha256，版本比对与改编跟版判定都靠它。

取值口径只有一处：`sha256` hex。以前 `api/content.py` 里叫 `_content_hash`，
`api/content_derivations.py` 反向 import 它；放到 service 后两边都用同一份，
避免「正文改了但哈希算法一处升级、另一处没升」这种只有线上才会暴露的问题。
"""

from __future__ import annotations

import hashlib


def content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()

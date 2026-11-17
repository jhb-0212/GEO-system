"""引用归因：只认「我们真发过的页面 URL」，不拿域名糊整站。

为什么要这样分两层（这是本模块的设计原则，改之前先读）：

1. **发布层（渠道效果）**：`publish_receipts.published_url` 是我们发布后真实上线的
   URL。引用 URL 与之相等（忽略协议、`www.`、末尾斜杠、utm/gclid 之类的跟踪参数，
   大小写按主机名处理）才算「我们的渠道页被引」。域名级匹配会把我们没写过的
   整站页面都算成渠道成果，指数虚高，所以**不再用域名决定 `channel_id`**。
2. **信源层（AI 从哪取证）**：任意第三方域名都进 `monitoring_citations.domain`，
   按域名聚合成信源分布（`stats.sources`）。归不到渠道的域名不再被塞进
   「渠道待归类队列」——那是两回事，混在一起会让人以为渠道目录里凭空多了一堆站点。

`channel_id` 的写入口径因此只有一处：URL 命中发布回执。命中不了的留空，
等真实发布后再由 `backfill_citation_channels.py` 回刷。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MonitoringCitation, PublishReceipt, PublishTask

# 这些参数只影响来源追踪，不影响页面本身；比对前先摘掉，避免同一页面因广告参数被判成两条。
TRACKING_PARAMS = ("utm_", "gclid", "fbclid", "spm", "from", "ref")

@dataclass(frozen=True)
class PublishedTarget:
    """一条发布回执对应的可归因目标。"""

    url_key: str
    published_url: str
    channel_id: uuid.UUID
    task_id: uuid.UUID
    version_id: uuid.UUID


def _is_tracking(name: str) -> bool:
    folded = name.casefold()
    return any(folded == prefix or folded.startswith(prefix) for prefix in TRACKING_PARAMS)


def url_key(raw_url: str | None) -> str:
    """URL 比对键：主机小写去 `www.`，忽略 http/https，去末尾斜杠与跟踪参数。

    query 里剩下的参数（如 `?p=123`）**保留**——那往往是文章 ID，删了会把两篇文章
    当成同一个页面；只摘掉纯追踪类参数。
    """
    if not raw_url:
        return ""
    value = raw_url.strip()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").casefold().strip(".")
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(
        sorted((name, item) for name, item in parse_qsl(parsed.query, keep_blank_values=True)
               if not _is_tracking(name))
    )
    return f"{host}{path}" + (f"?{query}" if query else "")


def build_published_index(db: Session, project_id: uuid.UUID) -> dict[str, PublishedTarget]:
    """本项目所有发布回执的 `url_key → 目标`；同一 URL 多条回执取最近一条。"""
    rows = db.execute(
        select(PublishReceipt, PublishTask)
        .join(PublishTask, PublishReceipt.task_id == PublishTask.id)
        .where(
            PublishReceipt.project_id == project_id,
            PublishTask.project_id == project_id,
        )
        .order_by(PublishReceipt.received_at.asc(), PublishReceipt.created_at.asc())
    ).all()
    index: dict[str, PublishedTarget] = {}
    for receipt, task in rows:
        key = url_key(receipt.published_url)
        if not key:
            continue
        # 后写入覆盖先写入 = 取最近一次发布
        index[key] = PublishedTarget(
            url_key=key,
            published_url=receipt.published_url,
            channel_id=task.channel_id,
            task_id=task.id,
            version_id=task.version_id,
        )
    return index


def resolve_published(index: dict[str, PublishedTarget], raw_url: str | None) -> PublishedTarget | None:
    """按引用 URL 找发布回执；找不到返回 None（不猜、不按域名兜底）。"""
    key = url_key(raw_url)
    return index.get(key) if key else None


def backfill_project_citations(
    db: Session, project_id: uuid.UUID, *, dry_run: bool = False
) -> dict:
    """把历史引用补上渠道归属：只处理 `channel_id IS NULL` 的行，按发布回执匹配。

    幂等：已归类的行不再参与；命中不了的保持为空（等真实发布后重跑）。
    """
    index = build_published_index(db, project_id)
    rows = db.scalars(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.channel_id.is_(None),
        )
    ).all()

    matched = 0
    unmatched = 0
    for row in rows:
        target = resolve_published(index, row.normalized_url or row.raw_url)
        if target is None:
            unmatched += 1
            continue
        matched += 1
        if not dry_run:
            row.channel_id = target.channel_id

    if not dry_run:
        db.commit()
    return {
        "candidates": len(rows),
        "matched": matched,
        "unmatched": unmatched,
        "published_urls": len(index),
    }

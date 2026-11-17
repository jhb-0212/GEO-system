"""发布可见性检测：发出去的页面能不能被搜索引擎检索到。

这是「发布 → 回执 → 被检索 → 被 AI 引用」中间那层的观测值，用来把"渠道发了没效果"
拆成两种情况：

- `matched=false` 且 `error_code` 为空 → 页面没进搜索索引（或被 `site` 过滤挡住了）；
- `matched=true` → 页面已可检索，后面 AI 没引用就与"收录"无关。

三条口径约束：
1. **不参与归因**：本模块只写 `publish_visibility_checks`，不碰 `monitoring_citations.channel_id`；
   渠道效果仍然只认"引用 URL 精确命中回执 URL"。
2. **命中只认 URL 精确相等**（`url_key` 归一后比较），不做标题相似匹配——标题像不等于同一个页。
3. **查失败要留痕**：上游报错写 `error_code`，`matched` 保持 false，绝不把"没查成"当成"没收录"。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentItem, ContentVersion, PublishReceipt, PublishTask, PublishVisibilityCheck
from app.services.citation_attribution import url_key

DEFAULT_ENDPOINT = "https://qianfan.baidubce.com/v2/ai_search/web_search"
DEFAULT_CREDENTIAL_REF = "QIANFAN_API_KEY"
# 千帆文档：`messages.content` 上限 72 字符，一个汉字算两个字符
MAX_QUERY_WEIGHT = 72
DEFAULT_TOP_K = 10
DEFAULT_TIMEOUT_SECONDS = 30.0

# 上游错误码 → 本地错误码；都写进 `error_code`，与"没被收录"区分开
HTTP_ERROR_CODES = {
    429: "http_429",
    401: "http_401",
    403: "http_403",
}


@dataclass(frozen=True)
class VisibilityResult:
    """一次检测的结果；`error_code` 非空表示没查成，此时 `matched` 恒为 false。"""

    matched: bool
    position: int | None
    matched_url: str | None
    result_count: int
    request_id: str | None
    error_code: str | None = None
    error_message: str | None = None


def _char_weight(char: str) -> int:
    """汉字按 2 计，其余按 1 计，与千帆的长度口径一致。"""
    return 2 if ord(char) > 0x2E80 else 1


def truncate_to_weight(text: str, limit: int = MAX_QUERY_WEIGHT) -> str:
    """按"权重"截断到上限，宁可少截也不超限。"""
    total = 0
    kept: list[str] = []
    for char in " ".join(text.split()):
        weight = _char_weight(char)
        if total + weight > limit:
            break
        total += weight
        kept.append(char)
    return "".join(kept).strip()


def build_query(title: str | None, published_url: str) -> str:
    """查询词：优先文章标题，没有标题时退回 URL 末段。两者都按权重截断。"""
    cleaned = truncate_to_weight(title or "")
    if cleaned:
        return cleaned
    tail = published_url.rstrip("/").rsplit("/", 1)[-1]
    return truncate_to_weight(tail.replace("-", " ").replace("_", " ")) or truncate_to_weight(
        published_url
    )


def site_of(published_url: str) -> str | None:
    """限定站点：回执 URL 的主机，去掉 `www.`（与 `url_key` 的归一保持一致）。"""
    key = url_key(published_url)
    if not key:
        return None
    host = key.split("/", 1)[0].split("?", 1)[0]
    return host or None


def _http_error_code(status: int, payload: dict[str, Any] | None) -> str:
    if status == 429 and payload:
        upstream = str(payload.get("code") or "").strip()
        if upstream:
            return upstream
    return HTTP_ERROR_CODES.get(status, f"http_{status}")


def search_web(
    client: httpx.Client,
    *,
    api_key: str,
    query: str,
    site: str | None,
    top_k: int = DEFAULT_TOP_K,
    endpoint: str = DEFAULT_ENDPOINT,
) -> tuple[list[dict[str, Any]], str | None, str | None, str | None]:
    """调千帆 web_search，返回 `(references, request_id, error_code, error_message)`。"""
    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": query}],
        "resource_type_filter": [{"type": "web", "top_k": max(1, min(50, top_k))}],
    }
    if site:
        body["search_filter"] = {"match": {"site": [site]}}

    try:
        response = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
    except httpx.TimeoutException as exc:
        return [], None, "timeout", str(exc)[:200]
    except httpx.HTTPError as exc:
        return [], None, "unreachable", str(exc)[:200]

    payload: dict[str, Any] | None = None
    try:
        decoded = response.json()
        if isinstance(decoded, dict):
            payload = decoded
    except ValueError:
        payload = None

    if response.status_code >= 400:
        return [], None, _http_error_code(response.status_code, payload), (
            (payload or {}).get("message") or f"HTTP {response.status_code}"
        )[:200]

    if payload is None:
        return [], None, "invalid_json", "上游返回不是 JSON 对象"

    # 千帆在异常时也可能返回 200，靠 body 里的 code 判断
    upstream_code = str(payload.get("code") or "").strip()
    if upstream_code:
        return [], payload.get("request_id"), upstream_code, str(payload.get("message") or "")[:200]

    raw_refs = payload.get("references")
    if not isinstance(raw_refs, list):
        return [], payload.get("request_id"), "no_references", "上游返回缺少 references"
    refs = [item for item in raw_refs if isinstance(item, dict)]
    return refs, payload.get("request_id"), None, None


def evaluate(
    references: list[dict[str, Any]],
    published_url: str,
    *,
    request_id: str | None = None,
    error_code: str | None = None,
) -> VisibilityResult:
    """按 URL 精确比对判定是否命中；命中取第一次出现的序号作为 `position`。"""
    if error_code:
        return VisibilityResult(
            matched=False,
            position=None,
            matched_url=None,
            result_count=len(references),
            request_id=request_id,
            error_code=error_code,
        )
    target = url_key(published_url)
    for index, item in enumerate(references, start=1):
        candidate = str(item.get("url") or "").strip()
        if candidate and url_key(candidate) == target:
            return VisibilityResult(
                matched=True,
                position=index,
                matched_url=candidate,
                result_count=len(references),
                request_id=request_id,
            )
    return VisibilityResult(
        matched=False,
        position=None,
        matched_url=None,
        result_count=len(references),
        request_id=request_id,
    )


def _receipt_title(db: Session, receipt: PublishReceipt) -> str | None:
    """回执 → 发布任务 → 内容版本 → 内容条目，取标题；链路断在任何一环都返回 None。"""
    task = db.get(PublishTask, receipt.task_id)
    if task is None:
        return None
    version = db.get(ContentVersion, task.version_id)
    if version is None:
        return None
    item = db.get(ContentItem, version.item_id)
    return item.title if item is not None else None


def check_receipt(
    db: Session,
    receipt: PublishReceipt,
    *,
    client: httpx.Client,
    api_key: str,
    top_k: int = DEFAULT_TOP_K,
    endpoint: str = DEFAULT_ENDPOINT,
    checked_at: datetime | None = None,
    dry_run: bool = False,
) -> VisibilityResult:
    """检测一条回执；`dry_run` 时只算不写。"""
    title = _receipt_title(db, receipt)
    query = build_query(title, receipt.published_url)
    site = site_of(receipt.published_url)
    references, request_id, error_code, error_message = search_web(
        client, api_key=api_key, query=query, site=site, top_k=top_k, endpoint=endpoint
    )
    result = evaluate(references, receipt.published_url, request_id=request_id, error_code=error_code)
    if error_code:
        result = VisibilityResult(
            matched=False,
            position=None,
            matched_url=None,
            result_count=result.result_count,
            request_id=request_id,
            error_code=error_code,
            error_message=error_message,
        )
    if not dry_run:
        row = PublishVisibilityCheck(
            project_id=receipt.project_id,
            receipt_id=receipt.id,
            checked_at=checked_at or datetime.now(timezone.utc),
            matched=result.matched,
            position=result.position,
            matched_url=result.matched_url,
            query=query,
            site=site,
            result_count=result.result_count,
            request_id=request_id,
            error_code=result.error_code,
        )
        db.add(row)
        db.flush()
    return result


def check_project(
    db: Session,
    project_id: uuid.UUID,
    *,
    client: httpx.Client,
    api_key: str,
    limit: int | None = None,
    top_k: int = DEFAULT_TOP_K,
    endpoint: str = DEFAULT_ENDPOINT,
    dry_run: bool = False,
    receipt_ids: list[uuid.UUID] | None = None,
) -> dict[str, int]:
    """批量检测本项目回执；返回计数汇总。"""
    stmt = (
        select(PublishReceipt)
        .where(PublishReceipt.project_id == project_id)
        .order_by(PublishReceipt.received_at.desc())
    )
    if receipt_ids:
        stmt = stmt.where(PublishReceipt.id.in_(receipt_ids))
    if limit:
        stmt = stmt.limit(limit)
    receipts = list(db.execute(stmt).scalars())

    summary = {"checked": 0, "matched": 0, "unmatched": 0, "failed": 0}
    for receipt in receipts:
        result = check_receipt(
            db,
            receipt,
            client=client,
            api_key=api_key,
            top_k=top_k,
            endpoint=endpoint,
            dry_run=dry_run,
        )
        summary["checked"] += 1
        if result.error_code:
            summary["failed"] += 1
        elif result.matched:
            summary["matched"] += 1
        else:
            summary["unmatched"] += 1
    return summary


def latest_checks(
    db: Session, project_id: uuid.UUID, *, limit: int = 50
) -> list[dict[str, Any]]:
    """最近检测结果，按回执分组只保留最新一条，供页面展示。"""
    rows = db.execute(
        select(
            PublishVisibilityCheck,
            PublishReceipt.published_url,
        )
        .join(PublishReceipt, PublishVisibilityCheck.receipt_id == PublishReceipt.id)
        .where(PublishVisibilityCheck.project_id == project_id)
        .order_by(PublishVisibilityCheck.checked_at.desc())
    ).all()

    seen: set[uuid.UUID] = set()
    items: list[dict[str, Any]] = []
    for check, published_url in rows:
        if check.receipt_id in seen:
            continue
        seen.add(check.receipt_id)
        items.append(
            {
                "receipt_id": str(check.receipt_id),
                "published_url": published_url,
                "checked_at": check.checked_at,
                "matched": check.matched,
                "position": check.position,
                "matched_url": check.matched_url,
                "query": check.query,
                "site": check.site,
                "result_count": check.result_count,
                "error_code": check.error_code,
            }
        )
        if len(items) >= limit:
            break
    return items

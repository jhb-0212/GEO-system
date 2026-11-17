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
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ContentItem, ContentVersion, PublishReceipt, PublishTask, PublishVisibilityCheck
from app.services.citation_attribution import url_key

DEFAULT_ENDPOINT = "https://qianfan.baidubce.com/v2/ai_search/web_search"
DEFAULT_CREDENTIAL_REF = "QIANFAN_API_KEY"
# 千帆文档写 `messages.content` 上限 72 字符（一个汉字算两个），但实测上游不校验：
# 权重 80 / 180 / 270 / 450 都正常返回 200 + 结果。所以 72 只是文档建议，按它截断会
# 白白丢掉标题后半段（真实标题常超 72 权重）。这里改用一个足够宽的安全上限兜底，
# 只防极端长的脏数据，不再牺牲召回。
MAX_QUERY_WEIGHT = 200
DEFAULT_TOP_K = 10
DEFAULT_TIMEOUT_SECONDS = 30.0

# 上游 QPS 很紧（实测 8 并发打 5 个 429、串行 0.59s/次已贴近限流线），
# 所以客户端自己限速并做 429 退避，避免批量检测把"被限流"记成"查询失败"。
DEFAULT_CALL_INTERVAL = 0.6
DEFAULT_RETRY_ON_429 = 2
DEFAULT_RETRY_BACKOFF = 1.0

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


_call_lock = threading.Lock()
_last_call_at = 0.0


def _wait_call_slot(interval: float) -> None:
    """全局限速：保证任意两次真实上游调用之间至少间隔 `interval` 秒。"""
    global _last_call_at
    if interval <= 0:
        return
    with _call_lock:
        wait = _last_call_at + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _http_error_code(status: int, payload: dict[str, Any] | None) -> str:
    """优先用上游 body 里的 `code`（401 的 216003、429 的 RATE_LIMIT_* 都在这里），否则退回 HTTP 状态。"""
    if payload:
        upstream = str(payload.get("code") or "").strip()
        if upstream:
            return upstream
    return HTTP_ERROR_CODES.get(status, f"http_{status}")


def _request_id_of(payload: dict[str, Any] | None) -> str | None:
    """上游成功用 `request_id`，报错用 `requestId`（驼峰），两个都要认。"""
    if not payload:
        return None
    return payload.get("request_id") or payload.get("requestId")


def _retryable_429(response: httpx.Response) -> bool:
    """QPS 限流可以等一下再打；配额/余额类 429 重试没有意义。"""
    try:
        payload = response.json()
    except ValueError:
        return True
    code = str((payload or {}).get("code") or "") if isinstance(payload, dict) else ""
    if not code:
        return True
    return "RATE_LIMIT" in code.upper()


def search_web(
    client: httpx.Client,
    *,
    api_key: str,
    query: str,
    site: str | None,
    top_k: int = DEFAULT_TOP_K,
    endpoint: str = DEFAULT_ENDPOINT,
    call_interval: float = DEFAULT_CALL_INTERVAL,
    retry_on_429: int = DEFAULT_RETRY_ON_429,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
) -> tuple[list[dict[str, Any]], str | None, str | None, str | None]:
    """调千帆 web_search，返回 `(references, request_id, error_code, error_message)`。

    上游对空查询词不报错（返回 200 + 一堆无关结果），所以空串在这里直接拦掉，
    既省钱也不会把"没查成"混成"未收录"。429 视为限流而非失败，退避重试几次再认输。
    """
    query = " ".join(query.split())
    if not query:
        return [], None, "empty_query", "查询词为空，未调用搜索接口"

    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": query}],
        "resource_type_filter": [{"type": "web", "top_k": max(1, min(50, top_k))}],
    }
    if site:
        body["search_filter"] = {"match": {"site": [site]}}

    response: httpx.Response | None = None
    for attempt in range(retry_on_429 + 1):
        _wait_call_slot(call_interval)
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
        if response.status_code != 429:
            break
        # 429 里只有 QPS 限流值得等；配额耗尽/余额不足重试也是同样的结果，白等 2 次
        if not _retryable_429(response) or attempt >= retry_on_429:
            break
        retry_after = response.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else retry_backoff * (attempt + 1)
        except ValueError:
            delay = retry_backoff * (attempt + 1)
        time.sleep(min(delay, 10.0))

    if response is None:  # 理论上到不了，兜底避免 mypy/静态检查报警
        return [], None, "unreachable", "未发出请求"

    payload: dict[str, Any] | None = None
    try:
        decoded = response.json()
        if isinstance(decoded, dict):
            payload = decoded
    except ValueError:
        payload = None

    if response.status_code >= 400:
        return [], _request_id_of(payload), _http_error_code(response.status_code, payload), (
            (payload or {}).get("message") or f"HTTP {response.status_code}"
        )[:200]

    if payload is None:
        return [], None, "invalid_json", "上游返回不是 JSON 对象"

    # 千帆在异常时也可能返回 200，靠 body 里的 code 判断
    upstream_code = str(payload.get("code") or "").strip()
    if upstream_code:
        return [], _request_id_of(payload), upstream_code, str(payload.get("message") or "")[:200]

    raw_refs = payload.get("references")
    if not isinstance(raw_refs, list):
        return [], _request_id_of(payload), "no_references", "上游返回缺少 references"
    refs = [item for item in raw_refs if isinstance(item, dict)]
    return refs, _request_id_of(payload), None, None


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
    if not target:
        # 回执 URL 无法归一（空串/非法协议）时不能拿空 key 去比，否则会匹配到同样归一出空的结果
        return VisibilityResult(
            matched=False,
            position=None,
            matched_url=None,
            result_count=len(references),
            request_id=request_id,
        )
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
    call_interval: float = DEFAULT_CALL_INTERVAL,
    retry_on_429: int = DEFAULT_RETRY_ON_429,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
) -> VisibilityResult:
    """检测一条回执；`dry_run` 时只算不写。"""
    title = _receipt_title(db, receipt)
    query = build_query(title, receipt.published_url)
    site = site_of(receipt.published_url)
    references, request_id, error_code, error_message = search_web(
        client,
        api_key=api_key,
        query=query,
        site=site,
        top_k=top_k,
        endpoint=endpoint,
        call_interval=call_interval,
        retry_on_429=retry_on_429,
        retry_backoff=retry_backoff,
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
    call_interval: float = DEFAULT_CALL_INTERVAL,
    retry_on_429: int = DEFAULT_RETRY_ON_429,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
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
            call_interval=call_interval,
            retry_on_429=retry_on_429,
            retry_backoff=retry_backoff,
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
    """最近检测结果，按回执分组只保留最新一条，供页面展示。

    去重放在 SQL 里（窗口函数），不再全表取回内存过滤：行数 = 回执数 × 检测次数，
    检测跑多了以后内存去重会越来越慢。
    """
    ranked = (
        select(
            PublishVisibilityCheck.id.label("id"),
            func.row_number()
            .over(
                partition_by=PublishVisibilityCheck.receipt_id,
                order_by=(PublishVisibilityCheck.checked_at.desc(), PublishVisibilityCheck.id.desc()),
            )
            .label("rn"),
        )
        .where(PublishVisibilityCheck.project_id == project_id)
        .subquery()
    )
    latest_ids = select(ranked.c.id).where(ranked.c.rn == 1)

    rows = db.execute(
        select(
            PublishVisibilityCheck,
            PublishReceipt.published_url,
        )
        .join(PublishReceipt, PublishVisibilityCheck.receipt_id == PublishReceipt.id)
        .where(
            PublishVisibilityCheck.project_id == project_id,
            PublishVisibilityCheck.id.in_(latest_ids),
        )
        .order_by(PublishVisibilityCheck.checked_at.desc())
        .limit(limit)
    ).all()

    return [
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
        for check, published_url in rows
    ]

"""回执「可访问」回抓：渠道侧三态的第一态。

三态的分工必须分清，否则报表会互相打架：

- **可访问**（本模块）：回抓 `published_url`，页面本身在不在；
- **已被收录**：搜索引擎能搜到该 URL（`publish_visibility` 既有能力）；
- **已被引用**：AI 回答里出现该 URL 或同域名引用（`monitoring_citations`）。

判定规则（不做"抓一次失败就等于被删"的推断）：

| 抓取结果 | 可访问 | 说明 |
|---|---|---|
| 2xx / 3xx | True | 正常 |
| 401 / 403 / 429 | True | 存在但限制访问（登录墙、反爬） |
| 404 / 410 | False | 明确的"没了" |
| 其他 4xx | None | 判定不了，只记状态码 |
| 5xx / 超时 / 连接失败 | None | 服务端或网络问题，记 error，不改历史结论 |
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PublishReceipt
from app.services import usage_metering

DEFAULT_TIMEOUT = 8.0
REACHABLE_STATUSES = {401, 403, 429}
GONE_STATUSES = {404, 410}

FetchResult = tuple[int | None, str | None]  # (status_code, error_code)


def _default_fetch(url: str) -> FetchResult:
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url)
        return response.status_code, None
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.HTTPError:
        return None, "network_error"


def judge(status_code: int | None, error_code: str | None) -> bool | None:
    if status_code is None:
        return None
    if status_code in GONE_STATUSES:
        return False
    if status_code < 400 or status_code in REACHABLE_STATUSES:
        return True
    return None


def run_checks(
    db: Session,
    project_id: uuid.UUID,
    *,
    limit: int = 20,
    fetch: Callable[[str], FetchResult] | None = None,
) -> dict:
    """按回执时间倒序回抓最多 limit 条，逐条落状态，单条失败不影响其余。

    不抛异常：批量检测里一条超时不该让整次检测失败，失败只体现在该条的 error 上。
    """
    fetcher = fetch or _default_fetch
    rows = db.scalars(
        select(PublishReceipt)
        .where(PublishReceipt.project_id == project_id)
        .order_by(PublishReceipt.received_at.desc(), PublishReceipt.id.desc())
        .limit(limit)
    ).all()

    reachable = unreachable = failed = 0
    started = time.perf_counter()
    for receipt in rows:
        status_code, error_code = fetcher(receipt.published_url)
        receipt.last_reachability_status = status_code
        receipt.last_reachability_error = error_code
        receipt.last_reachability_at = datetime.now(UTC)
        verdict = judge(status_code, error_code)
        # 网络类失败保留上次结论，不把"没查成"写成"不可访问"
        if verdict is not None:
            receipt.last_reachable = verdict
        if verdict is True:
            reachable += 1
        elif verdict is False:
            unreachable += 1
        else:
            failed += 1

    db.flush()
    # 回抓要花外部请求成本，但业务行上只留"最后一次状态"，没有可数的记录行：
    # 一个批次记一条消耗事件，数量=本次检查条数，`source_id` 用批次号天然唯一。
    usage_metering.record(
        db,
        project_id=project_id,
        metric="reachability",
        quantity=len(rows),
        source_type="reachability_batch",
        source_id=uuid.uuid4().hex,
        meta={"checked": len(rows), "reachable": reachable, "unreachable": unreachable, "failed": failed},
    )
    return {
        "checked": len(rows),
        "reachable": reachable,
        "unreachable": unreachable,
        "failed": failed,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def summary(db: Session, project_id: uuid.UUID) -> dict:
    rows = db.scalars(
        select(PublishReceipt).where(PublishReceipt.project_id == project_id)
    ).all()
    total = len(rows)
    checked = sum(1 for row in rows if row.last_reachability_at is not None)
    reachable = sum(1 for row in rows if row.last_reachable is True)
    unreachable = sum(1 for row in rows if row.last_reachable is False)
    return {
        "total": total,
        "checked": checked,
        "reachable": reachable,
        "unreachable": unreachable,
        "unknown": total - reachable - unreachable,
        "reachable_rate": round(reachable / checked, 4) if checked else None,
    }

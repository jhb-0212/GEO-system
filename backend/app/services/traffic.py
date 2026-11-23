"""B3 流量：访问事件的三个口径 + 地区/渠道分布。

三条口径并列给，互不换算（这是 B3 的取舍点）：

- PV（访问次数）：窗口内非机器人事件条数；
- 会话数：`visitor_session_id` 去重。有的埋点不带 session，这部分只进 PV；
- 去重访客：`visitor_ip_hash` 去重。没有 IP 的历史事件只进 PV。

所以三个数天然是「PV ≥ 会话 ≥ 去重访客」的包含关系，但**不做减法**：
不把「UV - 回访」当成新访客对外报，也不把「PV / UV」当成人均访问次数——
那些都是从这三个数二次推出来的指标，口径一变就不可比。页面只显示三个原始计数。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import TrafficEvent

UNKNOWN_LABEL = "未填写"
DIRECT_LABEL = "直接访问"


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _human_scope(project_id: uuid.UUID, since: datetime):
    return select(TrafficEvent).where(
        TrafficEvent.project_id == project_id,
        TrafficEvent.is_bot.is_(False),
        TrafficEvent.occurred_at >= since,
    )


def summary(db: Session, project_id: uuid.UUID, *, days: int = 30) -> dict:
    since = _since(days)
    pv = int(db.scalar(select(func.count()).select_from(_human_scope(project_id, since).subquery())) or 0)
    sessions = int(
        db.scalar(
            select(func.count(func.distinct(TrafficEvent.visitor_session_id))).where(
                TrafficEvent.project_id == project_id,
                TrafficEvent.is_bot.is_(False),
                TrafficEvent.occurred_at >= since,
                TrafficEvent.visitor_session_id.is_not(None),
            )
        )
        or 0
    )
    visitors = int(
        db.scalar(
            select(func.count(func.distinct(TrafficEvent.visitor_ip_hash))).where(
                TrafficEvent.project_id == project_id,
                TrafficEvent.is_bot.is_(False),
                TrafficEvent.occurred_at >= since,
                TrafficEvent.visitor_ip_hash.is_not(None),
            )
        )
        or 0
    )
    bot_events = int(
        db.scalar(
            select(func.count()).where(
                TrafficEvent.project_id == project_id,
                TrafficEvent.is_bot.is_(True),
                TrafficEvent.occurred_at >= since,
            )
        )
        or 0
    )

    region_rows = db.execute(
        select(
            TrafficEvent.visitor_region,
            func.count(),
            func.count(func.distinct(TrafficEvent.visitor_ip_hash)),
        )
        .where(
            TrafficEvent.project_id == project_id,
            TrafficEvent.is_bot.is_(False),
            TrafficEvent.occurred_at >= since,
        )
        .group_by(TrafficEvent.visitor_region)
    ).all()
    # coalesce 进 GROUP BY 会触发 GroupingError（绑定参数不一致），所以按原列分组、
    # Python 侧把 None 映射成「未填写」。
    by_region = sorted(
        (
            {"region": region or UNKNOWN_LABEL, "events": int(events), "visitors": int(visitors)}
            for region, events, visitors in region_rows
        ),
        key=lambda row: row["events"],
        reverse=True,
    )

    channel_rows = db.execute(
        select(
            TrafficEvent.utm_source,
            func.count(),
            func.count(func.distinct(TrafficEvent.visitor_ip_hash)),
        )
        .where(
            TrafficEvent.project_id == project_id,
            TrafficEvent.is_bot.is_(False),
            TrafficEvent.occurred_at >= since,
        )
        .group_by(TrafficEvent.utm_source)
    ).all()
    by_channel = sorted(
        (
            {"channel": channel or DIRECT_LABEL, "events": int(events), "visitors": int(visitors)}
            for channel, events, visitors in channel_rows
        ),
        key=lambda row: row["events"],
        reverse=True,
    )

    return {
        "days": days,
        "totals": {"pv": pv, "sessions": sessions, "visitors": visitors, "bot_events": bot_events},
        "by_region": by_region,
        "by_channel": by_channel,
        "notes": [
            "PV = 窗口内非机器人访问条数；机器人访问单列，不进任何分母。",
            "会话数按 session_id 去重，去重访客按 IP 哈希去重；两者分母不同，不做减法。",
            "历史事件没有 IP 哈希时只计入 PV，不参与去重访客。",
        ],
    }

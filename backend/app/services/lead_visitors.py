"""B4 获客：访客哈希口径 + 获客报表。

取舍清单 B4 的边界：
- 吸收：能从「访客去重 / 渠道 / 地区」三个角度看清获客结构；
- 拒绝：不存 IP 原文（只存加盐 sha256 前 32 位），也不做访客轨迹与画像。

因此上传口只收 `visitor_ip`，入库前在这里哈希；对外只回显哈希前缀，任何人拿不到可回溯的原始地址。
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Lead, LeadMessage


def hash_visitor(ip: str | None) -> str | None:
    """把访客地址变成稳定哈希；空值返回 None。

    加盐顺序是 `v{版本}:{盐}:{地址}`：
    - 盐优先取 `VISITOR_HASH_SALT`，没配就回落到 `SECRET_KEY`（既有哈希不变）；
    - 版本号进哈希输入，所以轮换盐时会自动换出一批新哈希，
      旧哈希留在库里但不再与新的可比，不会出现「换了盐还能对上同一个人」的假象。
    """
    clean = (ip or "").strip()
    if not clean:
        return None
    salt = (settings.visitor_hash_salt or settings.secret_key).strip()
    version = (settings.visitor_hash_salt_version or "1").strip()
    salted = f"v{version}:{salt}:{clean}".encode("utf-8")
    return hashlib.sha256(salted).hexdigest()[:32]


def mask_hash(value: str | None) -> str | None:
    """对外只露前 8 位，够区分访客又不足以做字典反查。"""
    return value[:8] if value else None


def visitor_report(db: Session, project_id: uuid.UUID) -> dict:
    """获客结构报表：总量 / 有效 / 去重访客 / 地区 / 渠道 / 未读留言。"""
    total = db.scalar(select(func.count()).select_from(Lead).where(Lead.project_id == project_id)) or 0
    valid = (
        db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(Lead.project_id == project_id, Lead.is_valid.is_(True))
        )
        or 0
    )
    # 只有带哈希的线索才算「可去重访客」；无哈希的（手工录入）单独计数，不参与去重
    distinct_visitors = (
        db.scalar(
            select(func.count(func.distinct(Lead.ip_hash))).where(
                Lead.project_id == project_id, Lead.ip_hash.is_not(None)
            )
        )
        or 0
    )
    with_hash = (
        db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(Lead.project_id == project_id, Lead.ip_hash.is_not(None))
        )
        or 0
    )

    region_rows = db.execute(
        select(Lead.visitor_region, func.count())
        .where(Lead.project_id == project_id)
        .group_by(Lead.visitor_region)
        .order_by(func.count().desc())
    ).all()
    channel_rows = db.execute(
        select(Lead.lead_source, func.count())
        .where(Lead.project_id == project_id)
        .group_by(Lead.lead_source)
        .order_by(func.count().desc())
    ).all()

    unread = (
        db.scalar(
            select(func.count())
            .select_from(LeadMessage)
            .where(
                LeadMessage.project_id == project_id,
                LeadMessage.author_role == "visitor",
                LeadMessage.is_read.is_(False),
            )
        )
        or 0
    )

    return {
        "total_leads": total,
        "valid_leads": valid,
        "distinct_visitors": distinct_visitors,
        "leads_with_visitor": with_hash,
        # 重复线索率 = 1 - 去重访客 / 带哈希线索；无带哈希线索时为 None（不拿 0 冒充「没有重复」）
        "repeat_rate": (
            round(1 - distinct_visitors / with_hash, 4) if with_hash else None
        ),
        "by_region": [
            {"region": region or "未填写", "count": count} for region, count in region_rows
        ],
        "by_source": [
            {"source": source or "未填写", "count": count} for source, count in channel_rows
        ],
        "unread_messages": unread,
    }

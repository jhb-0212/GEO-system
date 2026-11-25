"""跨渠道一致性检查：只报差异，不自动改稿。

边界（刻意写清，避免把提示做成“事实判决”）：
1. 自动比对只覆盖能确定性抽取的三类值：电话、金额、地址片段；
   组织名、服务范围、卖点表述仍交人工复核。
2. 只扫有当前版本且处于审核中/已批准/待发布/已发布的内容，草稿不算“对外口径”。
3. 母稿与渠道稿是否跟版、渠道台账与发布回执是否对得上，复用现有 `derivations` /
   `channel_anomalies` 的口径，不在这里重写一遍。
4. 地址只做“已批准地址/项目区域之外的新地址片段”提示，不直接判错：分支校区、
   临时活动地址可能合法，必须人工确认。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Channel, CompanyProfile, ContentItem, ContentVersion, Fact
from app.models.enums import ContentStatus, FactStatus, FactType
from app.services.channel_anomalies import detect_channel_anomalies
from app.services.derivations import page_derivations

SCAN_STATUSES = {
    ContentStatus.PENDING_REVIEW,
    ContentStatus.APPROVED,
    ContentStatus.SCHEDULED,
    ContentStatus.PENDING_PUBLISH,
    ContentStatus.PUBLISHED,
    ContentStatus.NEEDS_ATTENTION,
}

PHONE_PATTERN = re.compile(r"1[3-9]\d{9}|0\d{2,3}-?\d{7,8}")
MONEY_PATTERN = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(万元|万|元|块)")
ADDRESS_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}(?:省|市|区|县|镇|街道|路|街|号|大道|广场)")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _money_value(value: str) -> float | None:
    match = MONEY_PATTERN.search(value or "")
    if match is None:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    return amount * 10000 if unit in {"万", "万元"} else amount


def _fact_values(facts: list[Fact], fact_type: FactType) -> list[str]:
    return [fact.fact_value for fact in facts if fact.fact_type == fact_type and fact.fact_value.strip()]


def _conflict(
    *,
    code: str,
    severity: str,
    item: ContentItem,
    version: ContentVersion,
    channel_name: str | None,
    fact_key: str | None,
    fact_value: str | None,
    found: str,
    message: str,
    action: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "item_id": str(item.id),
        "version_id": str(version.id),
        "title": item.title,
        "channel_name": channel_name,
        "fact_key": fact_key,
        "fact_value": fact_value,
        "found": found,
        "message": message,
        "recommended_action": action,
    }


def consistency_report(
    db: Session,
    project_id: uuid.UUID,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """项目级一致性报告：未跟版、渠道异常、内容与权威事实冲突。"""
    facts = list(
        db.scalars(
            select(Fact).where(
                Fact.project_id == project_id,
                Fact.approval_status == FactStatus.APPROVED,
                Fact.superseded_by.is_(None),
            )
        )
    )
    contact_facts = _fact_values(facts, FactType.CONTACT)
    fee_facts = _fact_values(facts, FactType.COURSE_FEE)
    address_facts = _fact_values(facts, FactType.BASE_ADDRESS)
    approved_phones = {_digits(value) for value in contact_facts if _digits(value)}
    approved_money = {_money_value(value) for value in fee_facts if _money_value(value) is not None}
    approved_addresses = [re.sub(r"\s+", "", value) for value in address_facts if value.strip()]

    company = db.scalar(
        select(CompanyProfile).where(
            CompanyProfile.project_id == project_id,
            CompanyProfile.is_active.is_(True),
        )
    )
    known_regions = [str(item).strip() for item in (company.regions or []) if str(item).strip()] if company else []

    items = list(
        db.scalars(
            select(ContentItem).where(
                ContentItem.project_id == project_id,
                ContentItem.current_version_id.is_not(None),
                ContentItem.status.in_(SCAN_STATUSES),
            )
        )
    )
    version_ids = [item.current_version_id for item in items if item.current_version_id]
    versions = {
        version.id: version
        for version in db.scalars(
            select(ContentVersion).where(
                ContentVersion.project_id == project_id,
                ContentVersion.id.in_(version_ids),
            )
        )
    }
    channels = {
        channel.id: channel
        for channel in db.scalars(select(Channel).where(Channel.project_id == project_id))
    }

    conflicts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(item: ContentItem, version: ContentVersion, **kwargs: Any) -> None:
        key = (str(version.id), kwargs["code"], kwargs["found"])
        if key in seen:
            return
        seen.add(key)
        conflicts.append(
            _conflict(
                item=item,
                version=version,
                channel_name=channels[item.channel_id].name if item.channel_id in channels else None,
                **kwargs,
            )
        )

    for item in items:
        version = versions.get(item.current_version_id) if item.current_version_id else None
        if version is None:
            continue
        body = version.body or ""

        body_phones = {_digits(match.group(0)) for match in PHONE_PATTERN.finditer(body)}
        for phone in sorted(body_phones):
            if approved_phones and phone not in approved_phones:
                add(
                    item, version,
                    code="contact_mismatch",
                    severity="high",
                    fact_key="contact",
                    fact_value="；".join(contact_facts),
                    found=phone,
                    message=f"正文电话 {phone} 不在已批准联系方式事实中。",
                    action="核对号码是否为客户已批准对外号码；是则更新事实库，否则改正文。",
                )

        body_money = {value for match in MONEY_PATTERN.finditer(body) if (value := _money_value(match.group(0))) is not None}
        if approved_money and body_money:
            unknown_money = body_money - approved_money
            for amount in sorted(unknown_money):
                add(
                    item, version,
                    code="fee_mismatch",
                    severity="high",
                    fact_key="course_fee",
                    fact_value="；".join(fee_facts),
                    found=f"{amount:g}",
                    message=f"正文金额 {amount:g} 不在已批准费用事实中。",
                    action="核对价格是否为同一课程/同一口径；是则更新事实库，否则改正文。",
                )

        if approved_addresses:
            body_norm = re.sub(r"\s+", "", body)
            # 已批准地址完整出现时不再拆片段，避免把“地址在广州市…”误读成新地址；
            # 只有完整地址没出现，才把正文里的地址片段作为人工确认项。
            if not any(address in body_norm for address in approved_addresses):
                for token in {match.group(0) for match in ADDRESS_PATTERN.finditer(body)}:
                    token_norm = re.sub(r"\s+", "", token)
                    if any(region in token_norm for region in known_regions):
                        continue
                    add(
                        item, version,
                        code="address_unverified",
                        severity="warning",
                        fact_key="base_address",
                        fact_value="；".join(address_facts),
                        found=token,
                        message=f"正文地址片段「{token}」不在已批准地址事实或项目区域内，需人工确认是否为分支/活动地址。",
                        action="确认地址是否真实且属于该项目；是则补事实库，否则改正文。",
                    )

    stale_total, stale_rows = page_derivations(
        db, project_id, stale_only=True, page=1, page_size=min(limit, 20)
    )
    anomalies = detect_channel_anomalies(db, project_id)
    anomaly_rows = anomalies["anomalies"][:limit]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "contents_scanned": len(items),
            "approved_facts": len(facts),
            "fact_conflicts": len(conflicts),
            "stale_derivations": stale_total,
            "channel_anomalies": anomalies["counts"]["total"],
            "channel_anomalies_high": anomalies["counts"]["high"],
        },
        "fact_conflicts": conflicts[:limit],
        "stale_derivations": stale_rows,
        "channel_anomalies": anomaly_rows,
        "notes": [
            "自动比对只覆盖电话、金额、地址片段；组织名、服务范围、卖点表述仍需人工复核。",
            "只扫审核中、已批准、待发布、已发布和有异常的内容，草稿不纳入对外口径。",
            "地址片段只提示“未在已批准事实/项目区域中出现”，分支校区或活动地址可能合法。",
            "未跟版与渠道异常沿用现有改编、发布回执口径，不在本报告里另算一套。",
        ],
    }

"""投喂批次预检：五项逐条判定，任一不过即 blocked。

为什么要把预检放在后端：投喂是把「口径」推给 AI 平台，推错一次要全量回改。
所以门槛不能只写在页面提示里，必须由服务端在每次创建/重检时给出同一份结论。

五项：
1. 企业档案完整度 ≥ 80%（否则口径本身不完整）
2. 品牌设置已配置正式名与自有域名（否则无法被识别/统计信源）
3. 选中的每个内容版本都已审核通过
4. 目标渠道至少一个且均已准入（渠道是目标；引擎是结果，改用 expected_engines 表达期望）
5. 已审核 FAQ ≥ 1 条（投喂要带问答，不然平台只能被动复述品牌名）

第六项「期望被引引擎」只做记录与健康校验，永远不阻断——否则又会把口径倒回「引擎是目标」。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AiEngine, BrandProfile, Channel, CompanyProfile, ContentVersion, Faq
from app.models.enums import (
    ChannelApprovalStatus,
    ContentStatus,
    DistributionBatchStatus,
    FaqStatus,
)
# 企业档案完整度的唯一口径在 services/company_profile：服务层不能反向 import app.api。
from app.services.company_profile import brand_domains, serialize_profile
from app.services.state_machine import ensure_distribution_precheck_transition

COMPLETENESS_THRESHOLD = 80


def _company_check(db: Session, project_id: uuid.UUID) -> dict:
    profile = db.scalar(select(CompanyProfile).where(CompanyProfile.project_id == project_id))
    if profile is None:
        completeness = 0
    else:
        # 复用企业档案自己的完整度口径（与档案页显示的数字同源），不在这里重算一套
        completeness = int(
            serialize_profile(profile, domains=brand_domains(db, project_id)).get("completeness", 0)
        )
    ok = completeness >= COMPLETENESS_THRESHOLD
    return {
        "key": "company_profile",
        "label": "企业档案完整度",
        "ok": ok,
        "detail": f"当前 {completeness}%，门槛 {COMPLETENESS_THRESHOLD}%",
    }


def _brand_check(db: Session, project_id: uuid.UUID) -> dict:
    brand = db.scalar(
        select(BrandProfile).where(BrandProfile.project_id == project_id, BrandProfile.is_active.is_(True))
    )
    has_name = bool(brand and (brand.canonical_name or "").strip())
    has_domains = bool(brand and brand.owned_domains)
    ok = has_name and has_domains
    missing = []
    if not has_name:
        missing.append("正式名")
    if not has_domains:
        missing.append("自有域名")
    return {
        "key": "brand_profile",
        "label": "品牌设置",
        "ok": ok,
        "detail": "正式名与自有域名都已配置" if ok else f"缺：{'、'.join(missing)}",
    }


def _content_check(db: Session, version_ids: list[uuid.UUID], project_id: uuid.UUID) -> dict:
    if not version_ids:
        return {"key": "content_approved", "label": "内容版本", "ok": False, "detail": "未选择任何内容版本"}
    rows = db.execute(
        select(ContentVersion.id, ContentVersion.status).where(
            ContentVersion.project_id == project_id,
            ContentVersion.id.in_(version_ids),
        )
    ).all()
    found = {row.id: row.status for row in rows}
    missing = [str(version_id) for version_id in version_ids if version_id not in found]
    not_approved = [str(version_id) for version_id in version_ids if found.get(version_id) not in (None, ContentStatus.APPROVED)]
    ok = not missing and not not_approved
    if ok:
        detail = f"{len(version_ids)} 个版本均已审核通过"
    else:
        pieces = []
        if missing:
            pieces.append(f"{len(missing)} 个版本不属于当前项目")
        if not_approved:
            pieces.append(f"{len(not_approved)} 个版本未审核通过")
        detail = "；".join(pieces)
    return {"key": "content_approved", "label": "内容版本", "ok": ok, "detail": detail}


def _channel_check(db: Session, project_id: uuid.UUID, channel_ids: list[str]) -> dict:
    """目标必须是已准入渠道：内容投给渠道，不投给引擎。

    未审批渠道直接不通过——这才是「未准入不能发」的硬闸门在投喂侧的那一半。
    """
    if not channel_ids:
        return {"key": "target_channels", "label": "目标渠道", "ok": False, "detail": "未选择目标渠道"}
    try:
        parsed = [uuid.UUID(str(channel_id)) for channel_id in channel_ids]
    except ValueError:
        return {"key": "target_channels", "label": "目标渠道", "ok": False, "detail": "渠道 id 格式不合法"}
    rows = db.scalars(
        select(Channel).where(
            Channel.id.in_(parsed),
            Channel.project_id == project_id,
            Channel.approval_status == ChannelApprovalStatus.APPROVED,
        )
    ).all()
    ok = len(rows) == len(parsed)
    if ok:
        detail = f"{len(rows)} 个渠道均已准入"
    else:
        detail = f"{len(rows)} / {len(parsed)} 个渠道已准入，其余未通过审批"
    return {"key": "target_channels", "label": "目标渠道", "ok": ok, "detail": detail}


def _expected_engines_check(db: Session, engine_ids: list[str]) -> dict:
    """期望引擎只做记录与健康校验，不作为通过条件。

    引擎是结果不是目标；写错 id 提示，但不阻止投喂——否则又会把口径倒回去。
    """
    if not engine_ids:
        return {
            "key": "expected_engines",
            "label": "期望被引引擎",
            "ok": True,
            "detail": "未声明期望引擎（可选）",
        }
    try:
        parsed = [uuid.UUID(str(engine_id)) for engine_id in engine_ids]
    except ValueError:
        return {
            "key": "expected_engines",
            "label": "期望被引引擎",
            "ok": True,
            "detail": "引擎 id 格式不合法，已忽略该期望",
        }
    rows = db.scalars(select(AiEngine).where(AiEngine.id.in_(parsed))).all()
    return {
        "key": "expected_engines",
        "label": "期望被引引擎",
        "ok": True,
        "detail": f"{len(rows)} / {len(parsed)} 个引擎可识别；期望不参与阻断",
    }


def _faq_check(db: Session, project_id: uuid.UUID) -> dict:
    count = int(
        db.scalar(
            select(func.count()).where(Faq.project_id == project_id, Faq.status == FaqStatus.PUBLISHED)
        )
        or 0
    )
    return {
        "key": "faq_approved",
        "label": "已发布 FAQ",
        "ok": count >= 1,
        "detail": f"当前 {count} 条已发布问答" if count else "还没有发布状态的问答",
    }


def apply_precheck(
    db: Session,
    batch,
    *,
    version_ids: list[uuid.UUID],
    project_id: uuid.UUID,
    expected_engine_ids: list[str] | None = None,
) -> dict:
    """重算预检并回写批次状态，返回预检结果。

    这里是批次状态唯一的写入点：
    - 已确认投喂（dispatched）的批次不再被预检改写状态，历史结论不因后来数据变化而漂移；
    - 未确认的批次按预检结论在 `blocked ↔ ready` 之间走，同状态重复重检直接幂等。
    """
    precheck = run_precheck(
        db,
        project_id,
        version_ids=version_ids,
        channel_ids=list(batch.target_channel_ids or []),
        expected_engine_ids=list(expected_engine_ids or batch.expected_engines or []),
    )
    batch.precheck = precheck
    batch.last_checked_at = datetime.now(timezone.utc)
    if batch.status != DistributionBatchStatus.DISPATCHED:
        batch.status = ensure_distribution_precheck_transition(
            batch.status, DistributionBatchStatus(precheck["status"])
        )
    return precheck


def run_precheck(
    db: Session,
    project_id: uuid.UUID,
    *,
    version_ids: list[uuid.UUID],
    channel_ids: list[str],
    expected_engine_ids: list[str] | None = None,
) -> dict:
    checks = [
        _company_check(db, project_id),
        _brand_check(db, project_id),
        _content_check(db, version_ids, project_id),
        _channel_check(db, project_id, channel_ids),
        _faq_check(db, project_id),
        _expected_engines_check(db, list(expected_engine_ids or [])),
    ]
    ready = all(item["ok"] for item in checks)
    return {
        "ready": ready,
        "status": DistributionBatchStatus.READY.value if ready else DistributionBatchStatus.BLOCKED.value,
        "checks": checks,
        "failed": [item["key"] for item in checks if not item["ok"]],
    }

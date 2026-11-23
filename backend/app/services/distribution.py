"""投喂批次预检：五项逐条判定，任一不过即 blocked。

为什么要把预检放在后端：投喂是把「口径」推给 AI 平台，推错一次要全量回改。
所以门槛不能只写在页面提示里，必须由服务端在每次创建/重检时给出同一份结论。

五项：
1. 企业档案完整度 ≥ 80%（否则口径本身不完整）
2. 品牌设置已配置正式名与自有域名（否则无法被识别/统计信源）
3. 选中的每个内容版本都已审核通过
4. 目标平台至少一个且引擎存在
5. 已审核 FAQ ≥ 1 条（投喂要带问答，不然平台只能被动复述品牌名）
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.company import _brand_domains, _serialize as _serialize_company
from app.models import AiEngine, BrandProfile, CompanyProfile, ContentVersion, Faq
from app.models.enums import ContentStatus, DistributionBatchStatus, FaqStatus

COMPLETENESS_THRESHOLD = 80


def _company_check(db: Session, project_id: uuid.UUID) -> dict:
    profile = db.scalar(select(CompanyProfile).where(CompanyProfile.project_id == project_id))
    if profile is None:
        completeness = 0
    else:
        # 复用企业档案自己的完整度口径（与档案页显示的数字同源），不在这里重算一套
        completeness = int(
            _serialize_company(profile, domains=_brand_domains(db, project_id)).get("completeness", 0)
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


def _engine_check(db: Session, engine_ids: list[str]) -> dict:
    if not engine_ids:
        return {"key": "target_engines", "label": "目标平台", "ok": False, "detail": "未选择目标平台"}
    try:
        parsed = [uuid.UUID(str(engine_id)) for engine_id in engine_ids]
    except ValueError:
        return {"key": "target_engines", "label": "目标平台", "ok": False, "detail": "平台 id 格式不合法"}
    rows = db.scalars(
        select(AiEngine).where(AiEngine.id.in_(parsed), AiEngine.is_active.is_(True))
    ).all()
    ok = len(rows) == len(parsed)
    detail = f"{len(rows)} / {len(parsed)} 个平台可用" if not ok else f"{len(rows)} 个平台均可用"
    return {"key": "target_engines", "label": "目标平台", "ok": ok, "detail": detail}


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


def run_precheck(
    db: Session,
    project_id: uuid.UUID,
    *,
    version_ids: list[uuid.UUID],
    engine_ids: list[str],
) -> dict:
    checks = [
        _company_check(db, project_id),
        _brand_check(db, project_id),
        _content_check(db, version_ids, project_id),
        _engine_check(db, engine_ids),
        _faq_check(db, project_id),
    ]
    ready = all(item["ok"] for item in checks)
    return {
        "ready": ready,
        "status": DistributionBatchStatus.READY.value if ready else DistributionBatchStatus.BLOCKED.value,
        "checks": checks,
        "failed": [item["key"] for item in checks if not item["ok"]],
    }

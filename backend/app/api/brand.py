"""品牌实体配置接口：一个项目一份，读取用 monitoring.read，写入用 brand.manage。

设计要点：
- 用 PUT 做 upsert，前端不需要判断“是新建还是修改”；
- 读接口同时返回“生效词表”，让看板能直接显示当前到底按哪些词判定，
  避免出现“配了别名但报表没变化”这类无法自查的问题；
- 未配置时返回 `configured=false` 与回退后的词表，口径透明、且与采集侧一致。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, BrandProfileData, Envelope, ok
from app.db.session import get_db
from app.models import BrandProfile
from app.schemas import BrandProfileUpsert
from app.services.audit import record_audit
from app.services.brand_profile import build_vocabulary

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/brand-profile",
    tags=["品牌口径"],
    responses=COMMON_ERRORS,
)


def _serialize(profile: BrandProfile | None, vocabulary) -> dict:
    return {
        "configured": profile is not None,
        "canonical_name": profile.canonical_name if profile else None,
        "aliases": (profile.aliases or []) if profile else [],
        "identifiers": (profile.identifiers or []) if profile else [],
        "owned_domains": (profile.owned_domains or []) if profile else [],
        "notes": profile.notes if profile else None,
        "is_active": profile.is_active if profile else False,
        "updated_at": profile.updated_at if profile else None,
        # 生效词表：采集/统计实际用的就是这几组，前端据此解释报表口径。
        "effective_mention_terms": vocabulary.mention_terms,
        "effective_identifier_terms": vocabulary.identifier_terms,
        "effective_owned_domains": vocabulary.owned_domains,
    }


@router.get("", response_model=Envelope[BrandProfileData])
def get_brand_profile(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
) -> dict:
    profile = db.scalar(
        select(BrandProfile).where(BrandProfile.project_id == ctx.project.id)
    )
    vocabulary = build_vocabulary(db, ctx.project.id, project=ctx.project)
    return ok(_serialize(profile, vocabulary))


@router.put("", response_model=Envelope[BrandProfileData])
def upsert_brand_profile(
    payload: BrandProfileUpsert,
    ctx: ProjectContext = Depends(require_permission("brand.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """整体替换配置：传什么就是什么，避免局部更新留下旧别名。

    别名与唯一标识必须分开：把地址电话塞进 aliases 会把“提及率”污染成
    “提及或可识别率”，历史数据立刻不可比。这里显式拒绝这种写法。
    """
    identifier_set = {term.casefold() for term in (payload.identifiers or [])}
    alias_set = {term.casefold() for term in (payload.aliases or [])}
    overlap = identifier_set & alias_set
    if overlap:
        from app.core.errors import AppError

        raise AppError(
            "同一词条不能同时出现在 aliases 与 identifiers："
            "别名影响提及率，标识影响可识别率，混用会让两个指标互相污染",
            code="brand_term_overlap",
        )

    profile = db.scalar(
        select(BrandProfile)
        .where(BrandProfile.project_id == ctx.project.id)
        .with_for_update()
    )
    before = (
        {
            "canonical_name": profile.canonical_name,
            "aliases": profile.aliases,
            "identifiers": profile.identifiers,
            "owned_domains": profile.owned_domains,
            "is_active": profile.is_active,
        }
        if profile
        else None
    )
    if profile is None:
        profile = BrandProfile(project_id=ctx.project.id)
        db.add(profile)

    profile.canonical_name = payload.canonical_name
    profile.aliases = payload.aliases or []
    profile.identifiers = payload.identifiers or []
    profile.owned_domains = payload.owned_domains or []
    profile.notes = payload.notes
    profile.is_active = payload.is_active
    db.flush()

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="brand.profile.upsert",
        target_type="brand_profile",
        target_id=profile.id,
        payload={
            "before": before,
            "after": {
                "canonical_name": profile.canonical_name,
                "aliases": profile.aliases,
                "identifiers": profile.identifiers,
                "owned_domains": profile.owned_domains,
                "is_active": profile.is_active,
            },
            # 口径改动会影响历史与新数据的可比性，审计里明确标注作用面。
            "affects": "brand_mentioned / brand_identified / is_brand_related / sentiment / position",
        },
    )
    db.commit()
    vocabulary = build_vocabulary(db, ctx.project.id, project=ctx.project)
    return ok(_serialize(profile, vocabulary))

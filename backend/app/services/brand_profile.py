"""品牌实体配置的读写与词表解析：采集、回放、统计三处共用这一套口径。

三类词条的分工（这是本设计的核心边界，不要合并）：

1. `mention_terms`（正式名 + 别名）
   驱动 `monitoring_samples.brand_mentioned`。**只有点名才算提及**，口径严格，
   跨引擎、跨时间可比。改这里等于改历史口径，必须谨慎。
2. `identifier_terms`（地址、电话、公众号名等唯一标识）
   驱动 `monitoring_samples.brand_identified`。答案没点名、但给出了能唯一定位品牌的
   标识时记为「可识别」，**单独统计、不覆盖 brand_mentioned**。
   典型场景：问「基地在哪、怎么报名」，DeepSeek 答了详细地址和电话却没复述品牌名。
3. `owned_domains`（品牌自有域名）
   驱动引用的 `is_brand_related`，进而决定信源占比（品牌是否掌控了自己的信源）。

未配置品牌实体时一律回退到项目名/项目 code，保证历史样本口径不变。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrandProfile, Project


def clean_terms(values: object) -> list[str]:
    """清洗词条：去空白、丢空值、按 casefold 去重（保留首次出现的原写法与顺序）。"""
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        term = value.strip()
        if not term:
            continue
        folded = term.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        result.append(term)
    return result


def clean_domains(values: object) -> list[str]:
    """清洗域名：小写、去 www. 前缀与首尾点，与 normalize_url 的域名口径保持一致。"""
    domains: list[str] = []
    for term in clean_terms(values):
        domain = term.casefold().removeprefix("www.").strip(".")
        if domain and domain not in domains:
            domains.append(domain)
    return domains


@dataclass(frozen=True)
class BrandVocabulary:
    """一次采集/统计用到的全部品牌词表；构造后只读。"""

    mention_terms: list[str]
    identifier_terms: list[str]
    owned_domains: list[str]
    # 是否来自显式配置（False 表示回退到项目名，用于报表标注口径来源）
    configured: bool

    @property
    def has_identifiers(self) -> bool:
        return bool(self.identifier_terms)

    @property
    def has_owned_domains(self) -> bool:
        return bool(self.owned_domains)


EMPTY_VOCABULARY = BrandVocabulary(
    mention_terms=[], identifier_terms=[], owned_domains=[], configured=False
)


def get_brand_profile(db: Session, project_id: uuid.UUID) -> BrandProfile | None:
    """取项目当前生效的品牌实体；停用的配置视为未配置。"""
    return db.scalar(
        select(BrandProfile).where(
            BrandProfile.project_id == project_id,
            BrandProfile.is_active.is_(True),
        )
    )


def build_vocabulary(
    db: Session,
    project_id: uuid.UUID,
    *,
    project: Project | None = None,
) -> BrandVocabulary:
    """解析当前项目的品牌词表；未配置时回退到项目名 + 项目 code。

    回退分支必须保留：历史样本都是按项目名判定的，去掉回退会让新老数据口径不一致。
    """
    profile = get_brand_profile(db, project_id)
    project = project or db.get(Project, project_id)
    fallback = [term for term in ((project.name, project.code) if project else ()) if term]

    if profile is None:
        return BrandVocabulary(
            mention_terms=[term.strip() for term in fallback if term.strip()],
            identifier_terms=[],
            owned_domains=[],
            configured=False,
        )

    mention_terms = clean_terms([profile.canonical_name, *(profile.aliases or [])])
    return BrandVocabulary(
        mention_terms=mention_terms or [term.strip() for term in fallback if term.strip()],
        identifier_terms=clean_terms(profile.identifiers),
        owned_domains=clean_domains(profile.owned_domains),
        configured=True,
    )

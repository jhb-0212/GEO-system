"""给历史 AI 引用补建“未知被引域名”审核队列。

采集侧只在新样本写入时建队列（`monitoring_extraction.apply_answer_payload`）。
本模块处理历史引用：只读引用域名，跳过已登记渠道主域名/别名，按同一分类器
写 `citation_source_reviews`，不改引用归属、不创建渠道。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Channel,
    ChannelAlias,
    CitationSourceReview,
    MonitoringCitation,
)
from app.models.enums import ClassificationSource, SourceReviewStatus
from app.services.citation_classification import CLASSIFIER_VERSION, classify_citation, normalize_domain


def _registered_domains(db: Session, project_id: uuid.UUID) -> set[str]:
    domains: set[str] = set()
    for value in db.scalars(
        select(Channel.primary_domain).where(
            Channel.project_id == project_id,
            Channel.primary_domain.is_not(None),
        )
    ):
        normalized = normalize_domain(value)
        if normalized:
            domains.add(normalized)
    for value in db.scalars(
        select(ChannelAlias.domain).where(ChannelAlias.project_id == project_id)
    ):
        normalized = normalize_domain(value)
        if normalized:
            domains.add(normalized)
    return domains


def backfill_source_reviews(
    db: Session, project_id: uuid.UUID, *, dry_run: bool = False
) -> dict[str, int]:
    """幂等补建未知域名队列；返回 {domains, registered, candidates, created}。"""
    registered = _registered_domains(db, project_id)
    cited_domains = {
        normalized
        for value in db.scalars(
            select(MonitoringCitation.domain)
            .where(
                MonitoringCitation.project_id == project_id,
                MonitoringCitation.domain.is_not(None),
            )
            .distinct()
        )
        if (normalized := normalize_domain(value))
    }
    existing = {
        normalized
        for value in db.scalars(
            select(CitationSourceReview.domain).where(
                CitationSourceReview.project_id == project_id
            )
        )
        if (normalized := normalize_domain(value))
    }
    candidates = sorted(cited_domains - registered - existing)
    created = 0
    for domain in candidates:
        classification = classify_citation(domain=domain, url=f"https://{domain}/")
        db.add(
            CitationSourceReview(
                project_id=project_id,
                domain=domain,
                status=SourceReviewStatus.PENDING,
                suggested_source_category=classification.source_category,
                classification_source=ClassificationSource.RULE,
                classification_rule_version=CLASSIFIER_VERSION,
            )
        )
        created += 1
    if dry_run:
        db.rollback()
    else:
        db.flush()
    return {
        "domains": len(cited_domains),
        "registered": len(registered),
        "candidates": len(candidates),
        "created": 0 if dry_run else created,
    }

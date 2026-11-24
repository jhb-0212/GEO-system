"""自动机会规则：只生成待确认建议，不自动创建 Opportunity。

首期五条规则：
1. brand_absent：某题有效回答全部没有点名品牌；
2. competitor_outrank：品牌有位次但最优竞品位次更靠前；
3. source_gap：某题已复核引用达到阈值，但没有品牌相关引用；
4. fact_error：回答事实核验被判 wrong / expired；
5. stale_content：已发布官网页面超过 180 天未更新。

所有规则都用稳定 fingerprint 去重；人工采纳后才调用现有评分与机会模型。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AnswerFactClaim,
    MonitoringCompetitorMention,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Opportunity,
    OpportunitySuggestion,
    PublicPage,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    FactClaimVerdict,
    OpportunityGapType,
    OpportunitySuggestionRule,
    OpportunitySuggestionStatus,
    PagePublishStatus,
    SampleStatus,
)
from app.schemas.opportunities import OpportunityScoreFactors, OpportunityScoreWeights
from app.services.opportunities import score_opportunity

VALID_SAMPLE_STATUSES = (SampleStatus.HIT.value, SampleStatus.MISS.value)
STALE_DAYS = 180
SOURCE_GAP_MIN_CITATIONS = 3


@dataclass
class SuggestionDraft:
    rule_code: OpportunitySuggestionRule
    fingerprint: str
    title: str
    description: str
    gap_type: OpportunityGapType
    severity: str
    score: float
    question_id: uuid.UUID | None = None
    sample_id: uuid.UUID | None = None
    source_type: str | None = None
    source_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def _fingerprint(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _label(question_code: str | None, question_title: str | None) -> str:
    if question_code and question_title:
        return f"{question_code} · {question_title}"
    return question_title or question_code or "未命名问题"


def _valid_samples(db: Session, project_id: uuid.UUID, round_id: uuid.UUID | None):
    stmt = (
        select(
            MonitoringSample.id.label("sample_id"),
            MonitoringSample.brand_mentioned,
            MonitoringSample.brand_list_rank,
            Question.id.label("question_id"),
            Question.code,
            Question.title,
        )
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(Question, QuestionVersion.question_id == Question.id)
        .where(
            MonitoringSample.project_id == project_id,
            MonitoringTask.project_id == project_id,
            MonitoringSample.status.in_(VALID_SAMPLE_STATUSES),
        )
    )
    if round_id is not None:
        stmt = stmt.where(MonitoringTask.round_id == round_id)
    return db.execute(stmt).all()


def _brand_absent(db: Session, project_id: uuid.UUID, round_id: uuid.UUID | None) -> list[SuggestionDraft]:
    groups: dict[uuid.UUID, dict[str, Any]] = {}
    for row in _valid_samples(db, project_id, round_id):
        group = groups.setdefault(
            row.question_id,
            {"code": row.code, "title": row.title, "total": 0, "mentioned": 0, "samples": []},
        )
        group["total"] += 1
        if row.brand_mentioned:
            group["mentioned"] += 1
        elif len(group["samples"]) < 5:
            group["samples"].append(str(row.sample_id))
    drafts: list[SuggestionDraft] = []
    for question_id, group in groups.items():
        if group["total"] == 0 or group["mentioned"] > 0:
            continue
        drafts.append(
            SuggestionDraft(
                rule_code=OpportunitySuggestionRule.BRAND_ABSENT,
                fingerprint=_fingerprint("brand_absent", question_id, round_id),
                title=f"品牌缺席：{_label(group['code'], group['title'])}",
                description=f"该题 {group['total']} 条有效回答均未点名品牌，建议优先补可被 AI 引用的品牌内容或媒体稿。",
                gap_type=OpportunityGapType.MEDIA_REPORT,
                severity="high" if group["total"] >= 3 else "medium",
                score=4.0,
                question_id=question_id,
                sample_id=uuid.UUID(group["samples"][0]) if group["samples"] else None,
                source_type="question",
                source_id=str(question_id),
                evidence={"rule": "brand_absent", "valid_answers": group["total"], "sample_ids": group["samples"]},
            )
        )
    return drafts


def _competitor_outrank(db: Session, project_id: uuid.UUID, round_id: uuid.UUID | None) -> list[SuggestionDraft]:
    sample_rows = _valid_samples(db, project_id, round_id)
    rank_map = {row.sample_id: row for row in sample_rows if row.brand_list_rank is not None}
    if not rank_map:
        return []
    best_rows = db.execute(
        select(
            MonitoringCompetitorMention.sample_id,
            func.min(MonitoringCompetitorMention.position).label("best_rank"),
        )
        .where(MonitoringCompetitorMention.project_id == project_id)
        .group_by(MonitoringCompetitorMention.sample_id)
    ).all()
    best_map = {row.sample_id: int(row.best_rank) for row in best_rows if row.best_rank is not None}
    groups: dict[uuid.UUID, dict[str, Any]] = {}
    for sample_id, sample in rank_map.items():
        competitor_rank = best_map.get(sample_id)
        if competitor_rank is None or competitor_rank >= int(sample.brand_list_rank):
            continue
        group = groups.setdefault(
            sample.question_id,
            {"code": sample.code, "title": sample.title, "outrank": 0, "samples": [], "best": competitor_rank},
        )
        group["outrank"] += 1
        if len(group["samples"]) < 5:
            group["samples"].append({"sample_id": str(sample_id), "brand_rank": int(sample.brand_list_rank), "competitor_rank": competitor_rank})
        group["best"] = min(group["best"], competitor_rank)
    drafts: list[SuggestionDraft] = []
    for question_id, group in groups.items():
        evidence_samples = group["samples"]
        drafts.append(
            SuggestionDraft(
                rule_code=OpportunitySuggestionRule.COMPETITOR_OUTRANK,
                fingerprint=_fingerprint("competitor_outrank", question_id, round_id),
                title=f"竞品反超：{_label(group['code'], group['title'])}",
                description=f"{group['outrank']} 条有效回答中竞品位次优于品牌，最优竞品位次第 {group['best']}，建议补对应题的高可信信源。",
                gap_type=OpportunityGapType.MEDIA_REPORT,
                severity="high" if group["best"] <= 2 else "medium",
                score=4.5,
                question_id=question_id,
                sample_id=uuid.UUID(evidence_samples[0]["sample_id"]) if evidence_samples else None,
                source_type="question",
                source_id=str(question_id),
                evidence={"rule": "competitor_outrank", "outrank_samples": group["outrank"], "details": evidence_samples},
            )
        )
    return drafts


def _source_gap(db: Session, project_id: uuid.UUID, round_id: uuid.UUID | None) -> list[SuggestionDraft]:
    stmt = (
        select(
            MonitoringCitation.normalized_url,
            MonitoringCitation.domain,
            MonitoringCitation.is_brand_related,
            Question.id.label("question_id"),
            Question.code,
            Question.title,
        )
        .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(Question, QuestionVersion.question_id == Question.id)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringSample.project_id == project_id,
            MonitoringSample.status.in_(VALID_SAMPLE_STATUSES),
            MonitoringCitation.review_status == "manual_confirmed",
        )
    )
    if round_id is not None:
        stmt = stmt.where(MonitoringTask.round_id == round_id)
    rows = db.execute(stmt).all()
    groups: dict[uuid.UUID, dict[str, Any]] = {}
    for row in rows:
        group = groups.setdefault(
            row.question_id, {"code": row.code, "title": row.title, "total": 0, "brand": 0, "domains": set()}
        )
        group["total"] += 1
        if row.is_brand_related:
            group["brand"] += 1
        if row.domain and len(group["domains"]) < 8:
            group["domains"].add(row.domain)
    drafts: list[SuggestionDraft] = []
    for question_id, group in groups.items():
        if group["total"] < SOURCE_GAP_MIN_CITATIONS or group["brand"] > 0:
            continue
        drafts.append(
            SuggestionDraft(
                rule_code=OpportunitySuggestionRule.SOURCE_GAP,
                fingerprint=_fingerprint("source_gap", question_id, round_id),
                title=f"信源缺口：{_label(group['code'], group['title'])}",
                description=(
                    f"该题已有 {group['total']} 条已复核引用，但没有品牌相关引用；"
                    f"高频信源：{'、'.join(sorted(group['domains'])[:5]) or '未识别'}。"
                ),
                gap_type=OpportunityGapType.MEDIA_REPORT,
                severity="high" if group["total"] >= 6 else "medium",
                score=4.0,
                question_id=question_id,
                source_type="question",
                source_id=str(question_id),
                evidence={"rule": "source_gap", "confirmed_citations": group["total"], "domains": sorted(group["domains"])},
            )
        )
    return drafts


def _fact_error(db: Session, project_id: uuid.UUID) -> list[SuggestionDraft]:
    rows = db.scalars(
        select(AnswerFactClaim).where(
            AnswerFactClaim.project_id == project_id,
            AnswerFactClaim.verdict.in_([FactClaimVerdict.WRONG, FactClaimVerdict.EXPIRED]),
        )
    ).all()
    drafts: list[SuggestionDraft] = []
    for claim in rows:
        drafts.append(
            SuggestionDraft(
                rule_code=OpportunitySuggestionRule.FACT_ERROR,
                fingerprint=_fingerprint("fact_error", claim.id),
                title=f"事实纠错：{(claim.claim_text or '')[:40]}",
                description=f"AI 回答中的事实陈述被人工判定为 {claim.verdict.value}，需用权威事实与来源纠正。",
                gap_type=OpportunityGapType.FACT_CORRECTION,
                severity="high",
                score=5.0,
                sample_id=claim.sample_id,
                source_type="fact_claim",
                source_id=str(claim.id),
                evidence={
                    "rule": "fact_error",
                    "claim_id": str(claim.id),
                    "verdict": claim.verdict.value,
                    "claim_text": claim.claim_text,
                    "source_url": claim.source_url,
                },
            )
        )
    return drafts


def _stale_content(
    db: Session, project_id: uuid.UUID, *, now: datetime | None = None
) -> list[SuggestionDraft]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=STALE_DAYS)
    rows = db.scalars(
        select(PublicPage).where(
            PublicPage.project_id == project_id,
            PublicPage.publish_status == PagePublishStatus.PUBLISHED,
            PublicPage.last_published_at.is_not(None),
            PublicPage.last_published_at < cutoff,
        )
    ).all()
    drafts: list[SuggestionDraft] = []
    for page in rows:
        days = max(0, int(((now or datetime.now(timezone.utc)) - page.last_published_at).days))
        drafts.append(
            SuggestionDraft(
                rule_code=OpportunitySuggestionRule.STALE_CONTENT,
                fingerprint=_fingerprint("stale_content", page.id),
                title=f"内容过期：{page.title[:40]}",
                description=f"官网页面已 {days} 天未更新，AI 可能引用到过期信息；建议核对事实并更新发布。",
                gap_type=OpportunityGapType.OWN_PAGE,
                severity="medium",
                score=3.0,
                source_type="public_page",
                source_id=str(page.id),
                evidence={
                    "rule": "stale_content",
                    "page_id": str(page.id),
                    "url": page.url,
                    "last_published_at": page.last_published_at.isoformat(),
                    "days_since_publish": days,
                },
            )
        )
    return drafts


def generate_suggestions(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_id: uuid.UUID | None = None,
    limit: int = 80,
    now: datetime | None = None,
) -> dict[str, Any]:
    """生成/刷新建议；已采纳/已驳回的不覆盖，避免人工决定被规则重跑冲掉。"""
    drafts = (
        _brand_absent(db, project_id, round_id)
        + _competitor_outrank(db, project_id, round_id)
        + _source_gap(db, project_id, round_id)
        + _fact_error(db, project_id)
        + _stale_content(db, project_id, now=now)
    )
    drafts = drafts[: max(1, min(limit, 200))]
    created = updated = skipped = 0
    for draft in drafts:
        existing = db.scalar(
            select(OpportunitySuggestion).where(
                OpportunitySuggestion.project_id == project_id,
                OpportunitySuggestion.rule_code == draft.rule_code,
                OpportunitySuggestion.fingerprint == draft.fingerprint,
            )
        )
        generated_at = now or datetime.now(timezone.utc)
        if existing is None:
            db.add(
                OpportunitySuggestion(
                    project_id=project_id,
                    rule_code=draft.rule_code,
                    fingerprint=draft.fingerprint,
                    title=draft.title,
                    description=draft.description,
                    gap_type=draft.gap_type,
                    severity=draft.severity,
                    score=draft.score,
                    question_id=draft.question_id,
                    sample_id=draft.sample_id,
                    source_type=draft.source_type,
                    source_id=draft.source_id,
                    evidence=draft.evidence,
                    status=OpportunitySuggestionStatus.SUGGESTED,
                    generated_at=generated_at,
                )
            )
            created += 1
        elif existing.status == OpportunitySuggestionStatus.SUGGESTED:
            existing.title = draft.title
            existing.description = draft.description
            existing.gap_type = draft.gap_type
            existing.severity = draft.severity
            existing.score = draft.score
            existing.question_id = draft.question_id
            existing.sample_id = draft.sample_id
            existing.source_type = draft.source_type
            existing.source_id = draft.source_id
            existing.evidence = draft.evidence
            existing.generated_at = generated_at
            updated += 1
        else:
            skipped += 1
    db.flush()
    return {"created": created, "updated": updated, "skipped": skipped, "total": len(drafts)}


def _default_factors(draft: SuggestionDraft) -> dict[str, int]:
    if draft.rule_code == OpportunitySuggestionRule.FACT_ERROR:
        return {
            "business_value": 5,
            "competitor_gap": 4,
            "material_readiness": 4,
            "implementation_cost": 2,
            "channel_authorization": 2,
            "verifiability": 5,
        }
    if draft.rule_code == OpportunitySuggestionRule.STALE_CONTENT:
        return {
            "business_value": 3,
            "competitor_gap": 2,
            "material_readiness": 5,
            "implementation_cost": 2,
            "channel_authorization": 1,
            "verifiability": 4,
        }
    return {
        "business_value": 4,
        "competitor_gap": 5 if draft.rule_code == OpportunitySuggestionRule.COMPETITOR_OUTRANK else 4,
        "material_readiness": 3,
        "implementation_cost": 3,
        "channel_authorization": 3,
        "verifiability": 4,
    }


def accept_suggestion(
    db: Session,
    project_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None,
    owner_id: uuid.UUID | None = None,
    note: str | None = None,
) -> Opportunity:
    suggestion = db.scalar(
        select(OpportunitySuggestion).where(
            OpportunitySuggestion.project_id == project_id,
            OpportunitySuggestion.id == suggestion_id,
        )
    )
    if suggestion is None:
        raise ValueError("suggestion_missing")
    if suggestion.status != OpportunitySuggestionStatus.SUGGESTED:
        raise ValueError("suggestion_not_pending")
    factors = OpportunityScoreFactors(**_default_factors(suggestion))
    weights = OpportunityScoreWeights()
    raw, weight_values, priority = score_opportunity(factors, weights)
    evidence_refs = [
        {
            "type": "opportunity_suggestion",
            "id": str(suggestion.id),
            "rule_code": suggestion.rule_code.value,
            "source_type": suggestion.source_type,
            "source_id": suggestion.source_id,
        },
        *(
            [{"type": suggestion.source_type, "id": suggestion.source_id}]
            if suggestion.source_type and suggestion.source_id
            else []
        ),
    ]
    opportunity = Opportunity(
        project_id=project_id,
        title=suggestion.title[:255],
        gap_type=suggestion.gap_type,
        question_id=suggestion.question_id,
        sample_id=suggestion.sample_id,
        evidence_refs=evidence_refs,
        score_factors=raw,
        score_weights=weight_values,
        priority_score=priority,
        owner_id=owner_id,
        notes=note or suggestion.description,
    )
    db.add(opportunity)
    db.flush()
    suggestion.status = OpportunitySuggestionStatus.ACCEPTED
    suggestion.accepted_opportunity_id = opportunity.id
    suggestion.review_note = note
    suggestion.reviewed_by = actor_id
    suggestion.reviewed_at = datetime.now(timezone.utc)
    db.flush()
    return opportunity


def dismiss_suggestion(
    db: Session,
    project_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None,
    note: str | None = None,
) -> OpportunitySuggestion:
    suggestion = db.scalar(
        select(OpportunitySuggestion).where(
            OpportunitySuggestion.project_id == project_id,
            OpportunitySuggestion.id == suggestion_id,
        )
    )
    if suggestion is None:
        raise ValueError("suggestion_missing")
    if suggestion.status != OpportunitySuggestionStatus.SUGGESTED:
        raise ValueError("suggestion_not_pending")
    suggestion.status = OpportunitySuggestionStatus.DISMISSED
    suggestion.review_note = note
    suggestion.reviewed_by = actor_id
    suggestion.reviewed_at = datetime.now(timezone.utc)
    db.flush()
    return suggestion


def suggestion_payload(row: OpportunitySuggestion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "rule_code": row.rule_code.value,
        "title": row.title,
        "description": row.description,
        "gap_type": row.gap_type.value,
        "severity": row.severity,
        "score": row.score,
        "question_id": str(row.question_id) if row.question_id else None,
        "sample_id": str(row.sample_id) if row.sample_id else None,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "evidence": row.evidence or {},
        "status": row.status.value,
        "accepted_opportunity_id": str(row.accepted_opportunity_id) if row.accepted_opportunity_id else None,
        "review_note": row.review_note,
        "generated_at": row.generated_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def page_suggestions(
    db: Session,
    filters: list,
    *,
    page: int,
    page_size: int,
) -> tuple[int, list]:
    """建议列表的「计数 + 一页」：排序是分数优先、同分看新。"""
    from app.services.queries import page_of

    return page_of(
        db,
        OpportunitySuggestion,
        filters,
        order_by=(OpportunitySuggestion.score.desc(), OpportunitySuggestion.created_at.desc()),
        page=page,
        page_size=page_size,
    )

"""情绪原文统计：三档计数 + 原文列表 + 人工标注。

原文复用 `monitoring_citations`（仅人工复核通过），本模块不存原文副本；
标注只写 `sentiment_labels`，不改引用本身。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, SentimentItemData, SentimentSummaryData, ok
from app.core.errors import AppError
from app.db.session import get_db
from app.services.queries import fetch_one
from app.models import MonitoringCitation
from app.models.enums import CitationReviewStatus, SentimentPolarity
from app.schemas.sentiment import CorrectiveBatchIn, SentimentLabelIn
from app.services import generation, sentiment as sentiment_service
from app.services import sentiment_sampling
from app.services.audit import record_audit

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/sentiment",
    tags=["情绪原文"],
    responses=COMMON_ERRORS,
)


@router.get("/summary", response_model=Envelope[SentimentSummaryData])
def get_summary(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    return ok(sentiment_service.summary(db, ctx.project.id))


@router.get("/sampling", response_model=Envelope[dict])
def get_sampling(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    round_no: int = Query(1, ge=1, le=999, description="抽样轮次，决定抽哪批（规则固定可复算）"),
    size: int = Query(sentiment_sampling.DEFAULT_SIZE, ge=1, le=60),
    scope: str = Query("brand_related", pattern="^(brand_related|all)$"),
) -> dict:
    """双人盲评队列：稳定抽样 + 负面风险预排序（预排序只决定阅读顺序，不进比率）。"""
    return ok(sentiment_sampling.sampling_queue(db, ctx.project.id, round_no=round_no, size=size, scope=scope))


@router.get("/consensus", response_model=Envelope[dict])
def get_consensus(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    round_no: int = Query(1, ge=1, le=999),
    size: int = Query(sentiment_sampling.DEFAULT_SIZE, ge=1, le=60),
    scope: str = Query("brand_related", pattern="^(brand_related|all)$"),
    cumulative: bool = Query(False, description="true=把第 1..round_no 轮的抽样并起来算"),
) -> dict:
    """抽样共识：至少两人同档才算共识；不足 50 条不出正向率。"""
    if cumulative:
        return ok(sentiment_sampling.cumulative_consensus(
            db, ctx.project.id, size=size, scope=scope, max_rounds=round_no
        ))
    return ok(sentiment_sampling.consensus(db, ctx.project.id, round_no=round_no, size=size, scope=scope))


@router.get("/items", response_model=PagedEnvelope[SentimentItemData])
def list_items(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    polarity: str | None = Query(None, pattern="^(positive|neutral|negative|unlabeled)$"),
    sort: str = Query("credibility", pattern="^(credibility|recent)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    result = sentiment_service.items(
        db, ctx.project.id, polarity=polarity, sort=sort, page=page, page_size=page_size
    )
    return {"data": result["data"], "meta": result["meta"]}


@router.post("/{citation_id}/label", response_model=Envelope[dict])
def label_item(
    citation_id: uuid.UUID,
    payload: SentimentLabelIn,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    citation = fetch_one(
        db, MonitoringCitation, project_id=ctx.project.id, id=citation_id
    )
    if citation is None:
        raise AppError("引文不存在或不属于当前项目", code="citation_not_found")
    if citation.review_status != CitationReviewStatus.MANUAL_CONFIRMED:
        raise AppError("只能给人工复核通过的引用打情绪标注", code="citation_not_confirmed")

    result = sentiment_service.label_citation(
        db,
        ctx.project.id,
        citation_id=citation_id,
        polarity=SentimentPolarity(payload.polarity),
        grade=payload.grade,
        note=payload.note,
        actor_id=ctx.user.id,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="sentiment.label",
        target_type="monitoring_citation",
        target_id=citation_id,
        payload={"polarity": payload.polarity},
    )
    db.commit()
    return ok(result)


@router.post("/{citation_id}/corrective-batch", status_code=201, response_model=Envelope[dict])
def create_corrective_batch(
    citation_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
    payload: CorrectiveBatchIn | None = None,
) -> dict:
    """负面标注的处置动作：把这条引用变成一篇纠正稿，进生成批次的审稿队列。

    系统不判舆情，只接手「人已经判定为负面」之后要做的事：
    出稿仍然是模板合成 + 人工审稿 + 不自动发布，只是选题证据从机会缺口换成了这条引用。
    """
    snapshot = generation.create_remediation_batch(
        db,
        ctx.project.id,
        citation_id,
        name=(payload.name if payload else None),
        note=(payload.note if payload else None),
        created_by=ctx.user.id,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="sentiment.corrective_batch",
        target_type="monitoring_citation",
        target_id=citation_id,
        payload={"batch_id": str(snapshot["batch_id"]), "reused": snapshot["reused"]},
    )
    db.commit()
    return ok(snapshot)

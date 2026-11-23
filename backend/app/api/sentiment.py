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
from app.models import MonitoringCitation
from app.models.enums import CitationReviewStatus, SentimentPolarity
from app.schemas.sentiment import SentimentLabelIn
from app.services import sentiment as sentiment_service
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
    citation = db.scalar(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == ctx.project.id,
            MonitoringCitation.id == citation_id,
        )
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

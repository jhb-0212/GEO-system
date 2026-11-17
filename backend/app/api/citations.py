"""引用复核接口（B6）：列表只读，归属确认/驳回走 evidence.review。

待归类队列口径（验收用例 C4）：只返回 review_pending 渠道，按项目隔离；
未知域名先进入待归类渠道，人工归类结果不被自动识别覆盖。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    CitationData,
    Envelope,
    PagedEnvelope,
    UnknownDomainItem,
    ok,
    ok_page,
)
from app.core.errors import AppError, ResourceMissingError
from app.db.session import get_db
from app.models import Channel, Competitor, MonitoringCitation, MonitoringSample
from app.models.enums import ChannelStatus, CitationReviewStatus
from app.schemas import CitationReviewRequest
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/citations",
    tags=["引用复核"],
    responses=COMMON_ERRORS,
)


def _citation_payload(row: MonitoringCitation) -> dict:
    return {
        "citation_id": str(row.id),
        "sample_id": str(row.sample_id),
        "raw_url": row.raw_url,
        "normalized_url": row.normalized_url,
        "domain": row.domain,
        "citation_usage": row.citation_usage.value if row.citation_usage else None,
        "is_brand_related": row.is_brand_related,
        "review_status": row.review_status.value,
        "channel_id": str(row.channel_id) if row.channel_id else None,
        "competitor_id": str(row.competitor_id) if row.competitor_id else None,
        "reviewed_at": row.reviewed_at,
        "review_note": row.review_note,
    }


@router.get("/unknown-domains", response_model=PagedEnvelope[UnknownDomainItem])
def list_unknown_domains(
    # B6 权限码按 C 拍板复用 channel.read，不新增 editor 独有读码。
    ctx: ProjectContext = Depends(require_permission("channel.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    # 待归类队列：只返回 review_pending 渠道，按项目隔离（验收用例 C4）。
    total = (
        db.scalar(
            select(func.count())
            .select_from(Channel)
            .where(
                Channel.project_id == ctx.project.id,
                Channel.status == ChannelStatus.REVIEW_PENDING,
            )
        )
        or 0
    )
    channels = db.scalars(
        select(Channel)
        .where(
            Channel.project_id == ctx.project.id,
            Channel.status == ChannelStatus.REVIEW_PENDING,
        )
        .order_by(Channel.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = []
    if channels:
        # 一条聚合出引用数/样本数/最近采样，替代原先“每个渠道两次查询 + 全量加载引用”
        stats_rows = db.execute(
            select(
                MonitoringCitation.channel_id,
                func.count().label("citation_count"),
                func.count(func.distinct(MonitoringCitation.sample_id)).label("sample_count"),
                func.max(MonitoringSample.sampled_at).label("last_sampled_at"),
            )
            .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
            .where(
                MonitoringCitation.project_id == ctx.project.id,
                MonitoringCitation.channel_id.in_([channel.id for channel in channels]),
                MonitoringSample.project_id == ctx.project.id,
            )
            .group_by(MonitoringCitation.channel_id)
        ).all()
        stats = {row.channel_id: row for row in stats_rows}
    else:
        stats = {}

    for channel in channels:
        row = stats.get(channel.id)
        items.append(
            {
                "channel_id": str(channel.id),
                "code": channel.code,
                "name": channel.name,
                "primary_domain": channel.primary_domain,
                "citation_count": int(row.citation_count) if row else 0,
                "sample_count": int(row.sample_count) if row else 0,
                "last_sampled_at": row.last_sampled_at if row else None,
            }
        )
    return ok_page(items, page=page, page_size=page_size, total=total)


@router.get("", response_model=PagedEnvelope[CitationData])
def list_citations(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    review_status: CitationReviewStatus | None = None,
    sample_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    filters = [MonitoringCitation.project_id == ctx.project.id]
    if review_status is not None:
        filters.append(MonitoringCitation.review_status == review_status)
    if sample_id is not None:
        filters.append(MonitoringCitation.sample_id == sample_id)

    total = (
        db.scalar(select(func.count()).select_from(MonitoringCitation).where(*filters)) or 0
    )
    rows = db.scalars(
        select(MonitoringCitation)
        .where(*filters)
        .order_by(MonitoringCitation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [_citation_payload(r) for r in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.patch("/{citation_id}", response_model=Envelope[CitationData])
def review_citation(
    citation_id: uuid.UUID,
    payload: CitationReviewRequest,
    ctx: ProjectContext = Depends(require_permission("evidence.review")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(
        db,
        MonitoringCitation,
        ctx.project.id,
        resource="monitoring_citation",
        id=citation_id,
        for_update=True,
    )
    if payload.review_status == CitationReviewStatus.AUTO:
        raise AppError("手动复核不能回写 auto 状态", code="invalid_review_status")

    row.review_status = payload.review_status
    # 备注与归属字段同为部分更新：显式传值（含 null）才覆盖，不传保留原值。
    if "review_note" in payload.model_fields_set:
        row.review_note = payload.review_note
    row.reviewed_by = ctx.user.id
    row.reviewed_at = datetime.now(timezone.utc)

    # 归属改挂（C 拍板）：字段在请求体中显式出现才处理；null 表示清空映射；
    # 传值须属当前项目且存在，否则 404 resource_missing（不暴露存在性）。raw_url 不在本接口可改字段内。
    if "channel_id" in payload.model_fields_set:
        if payload.channel_id is None:
            row.channel_id = None
        else:
            channel = db.scalar(
                select(Channel).where(
                    Channel.id == payload.channel_id,
                    Channel.project_id == ctx.project.id,
                )
            )
            if channel is None:
                raise ResourceMissingError("渠道不存在或不属于本项目")
            row.channel_id = channel.id

    if "competitor_id" in payload.model_fields_set:
        if payload.competitor_id is None:
            row.competitor_id = None
        else:
            competitor = db.scalar(
                select(Competitor).where(
                    Competitor.id == payload.competitor_id,
                    Competitor.project_id == ctx.project.id,
                )
            )
            if competitor is None:
                raise ResourceMissingError("竞品不存在或不属于本项目")
            row.competitor_id = competitor.id

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citation.review",
        target_type="monitoring_citation",
        target_id=row.id,
        payload={
            "review_status": payload.review_status.value,
            "channel_id": str(row.channel_id) if row.channel_id else None,
            "competitor_id": str(row.competitor_id) if row.competitor_id else None,
        },
    )
    db.commit()
    return ok(_citation_payload(row))

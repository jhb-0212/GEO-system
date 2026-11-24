"""引用证据与来源分类接口。

- 引用列表 / 复核保持发布归因不变：`channel_id` 只认发布回执 URL；
- `/unknown-domains` 保留渠道台账的待归类队列（历史兼容）；
- `/source-reviews` 是 AI 引用里的独立未知域名队列，只做来源分类，不创建发布渠道。
"""

import csv
import io
import uuid
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    CitationData,
    Envelope,
    PagedEnvelope,
    SourceReviewItem,
    UnknownDomainItem,
    ok,
    ok_page,
)
from app.core.errors import AppError, ResourceMissingError
from app.db.session import get_db
from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    CitationSourceReview,
    Competitor,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    ChannelStatus,
    CitationReviewStatus,
    ClassificationSource,
    SourceReviewStatus,
)
from app.schemas.citations import (
    CitationPageTypeRequest,
    CitationReviewRequest,
    CitationSourceBulkClassifyRequest,
    CitationSourceClassifyRequest,
)
from app.services.channel_access import ensure_channel_approved
from app.services.audit import record_audit, record_export
from app.services.excerpts import excerpt
from app.services.citation_classification import CLASSIFIER_VERSION
from app.services.page_type_rules import reclassify as reclassify_page_types
from app.services.page_title_backfill import backfill_titles
from app.services.brand_related_candidates import brand_related_candidates
from app.services.source_category_propagation import source_category_candidates
from app.services.source_domain_evidence import collect_domain_evidence
from app.services.source_domain_registry import classify_domains, domain_overview
from app.services.csv_safety import safe_csv_row
from app.services.export_guard import ensure_sync_export_allowed
from app.services.project_scope import require_scoped_row
from app.services.source_review_queue import page_source_reviews
from app.services.state_machine import ensure_source_review_transition

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/citations",
    tags=["引用复核"],
    responses=COMMON_ERRORS,
)


@router.get("/page-type-preview", response_model=Envelope[dict])
def preview_page_type_reclassify(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000, description="本次最多扫多少条 other 引用"),
    mode: str = Query("path", pattern="^(path|content)$", description="path=URL 规则，content=标题/摘要词表"),
) -> dict:
    """引用页型规则重判的预览：不改库，只返回将变化的条数与对照样例。"""
    return ok(reclassify_page_types(db, ctx.project.id, dry_run=True, limit=limit, mode=mode))


@router.post("/page-type-reclassify", response_model=Envelope[dict])
def apply_page_type_reclassify(
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000, description="本次最多重判多少条"),
    mode: str = Query("path", pattern="^(path|content)$", description="path=URL 规则，content=标题/摘要词表"),
) -> dict:
    """按规则重判 `page_type=other` 的引用；人工改过的行永不覆盖。"""
    result = reclassify_page_types(db, ctx.project.id, dry_run=False, limit=limit, mode=mode)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citations.page_type.reclassify",
        target_type="citation_batch",
        payload={
            "rule_version": result["rule_version"],
            "mode": result["mode"],
            "changed": result["scope"]["changed"],
            "scanned": result["scope"]["scanned"],
            "by_target": result["by_target"],
        },
    )
    db.commit()
    return ok(result)


@router.post("/page-title-backfill", response_model=Envelope[dict])
def backfill_page_titles(
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200, description="本次最多探测多少条无标题引用"),
    apply: bool = Query(False, description="false=只探测，true=把取到的标题写回库"),
) -> dict:
    """给 `page_type=other` 且无标题的引用回抓页面标题，供内容级形态判定使用。"""
    result = backfill_titles(db, ctx.project.id, limit=limit, dry_run=not apply)
    if apply:
        record_audit(
            db,
            project_id=ctx.project.id,
            actor_id=ctx.user.id,
            action="citations.title.backfill",
            target_type="citation_batch",
            payload={
                "titled": result["scope"]["titled"],
                "candidates": result["scope"]["candidates"],
                "by_status": result["by_status"],
            },
        )
        db.commit()
    return ok(result)


@router.get("/brand-related-candidates", response_model=Envelope[dict])
def preview_brand_related(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=2000, description="本次最多扫多少条已复核引用"),
    sample_limit: int = Query(20, ge=1, le=100, description="返回的对照样例条数"),
) -> dict:
    """品牌相关性候选：标题/摘要命中品牌词表的已复核引用，只预览不改库。"""
    return ok(brand_related_candidates(db, ctx.project.id, apply=False, limit=limit, sample_limit=sample_limit))


@router.post("/brand-related-candidates/backfill", response_model=Envelope[dict])
def apply_brand_related(
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=2000, description="本次最多处理多少条"),
) -> dict:
    """把候选标记为品牌相关（只写 true，不写 false）；落审计。"""
    result = brand_related_candidates(db, ctx.project.id, apply=True, limit=limit)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citations.brand_related.backfill",
        target_type="citation_batch",
        payload={
            "candidates": result["scope"]["candidates"],
            "changed": result["scope"]["changed"],
            "by_term": result["by_term"],
        },
    )
    db.commit()
    return ok(result)


@router.get("/source-category-candidates", response_model=Envelope[dict])
def preview_source_category(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """同站类别传播：把同站已有的已知来源类别复制给 unknown/other 行，只预览。"""
    return ok(source_category_candidates(db, ctx.project.id, apply=False, limit=limit))


@router.post("/source-category-propagate", response_model=Envelope[dict])
def apply_source_category(
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """执行同站类别传播；只写已知传未知，落审计。"""
    result = source_category_candidates(db, ctx.project.id, apply=True, limit=limit)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citations.source_category.propagate",
        target_type="citation_batch",
        payload={
            "sites": result["scope"]["sites_with_evidence"],
            "affected": result["scope"]["affected_citations"],
            "changed": result["scope"]["changed"],
        },
    )
    db.commit()
    return ok(result)


@router.get("/source-domains", response_model=Envelope[dict])
def preview_source_domains(
    ctx: ProjectContext = Depends(require_permission("monitoring.read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """站点级来源归类：一次判一个站点，覆盖该站全部引用。"""
    return ok(domain_overview(db, ctx.project.id, apply=False, limit=limit))


@router.post("/source-domains/apply", response_model=Envelope[dict])
def apply_source_domains(
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """按域名身份表写入站点类别（只写身份表命中的站点，落审计）。"""
    result = domain_overview(db, ctx.project.id, apply=True, limit=limit)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citations.source_domain.apply",
        target_type="citation_batch",
        payload={
            "sites": result["scope"]["suggested_sites"],
            "changed": result["scope"]["changed"],
        },
    )
    db.commit()
    return ok(result)


@router.post("/source-domains/evidence", response_model=Envelope[dict])
def collect_source_domain_evidence(
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
    limit: int = Query(0, ge=0, le=200),
    refresh: bool = Query(False),
) -> dict:
    """抓取待判站点的首页标题/描述，作为人工判定依据（不写类别）。"""
    result = collect_domain_evidence(db, ctx.project.id, limit=limit, refresh=refresh)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citations.source_domain.evidence",
        target_type="citation_batch",
        payload={"fetched": result["fetched"], "ok": result["ok"]},
    )
    db.commit()
    return ok(result)


@router.post("/source-domains/classify", response_model=Envelope[dict])
def classify_source_domains(
    payload: dict,
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
) -> dict:
    """人工判定：按站点给类别，整站生效，落审计（依据 note 一并记录）。"""
    decisions = payload.get("decisions") or []
    if not isinstance(decisions, list) or not decisions:
        raise HTTPException(status_code=400, detail="decisions 不能为空")
    result = classify_domains(db, ctx.project.id, decisions, apply=True)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citations.source_domain.classify",
        target_type="citation_batch",
        payload={"sites": len(decisions), "changed": result["changed"], "decisions": decisions[:50]},
    )
    db.commit()
    return ok(result)


def _citation_payload(row: MonitoringCitation) -> dict:
    return {
        "citation_id": str(row.id),
        "sample_id": str(row.sample_id),
        "raw_url": row.raw_url,
        "normalized_url": row.normalized_url,
        "domain": row.domain,
        "title": row.title,
        "site_name": row.site_name,
        "snippet": row.snippet,
        "published_at": row.published_at,
        "position": row.position,
        "source_category": row.source_category.value if row.source_category else None,
        "page_type": row.page_type.value if row.page_type else None,
        "classification_source": (
            row.classification_source.value if row.classification_source else None
        ),
        "classification_rule_version": row.classification_rule_version,
        "citation_usage": row.citation_usage.value if row.citation_usage else None,
        "is_brand_related": row.is_brand_related,
        "review_status": row.review_status.value,
        "channel_id": str(row.channel_id) if row.channel_id else None,
        "competitor_id": str(row.competitor_id) if row.competitor_id else None,
        "reviewed_at": row.reviewed_at,
        "review_note": row.review_note,
    }


def _answer_excerpt(value: str | None, limit: int = 160) -> str | None:
    """引用列表沿用硬截断（不加省略号），长度口径见 services.excerpts。"""
    return excerpt(value, limit, ellipsis=False)


@router.get("/answer-options")
def list_citation_answer_options(
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
    q: str | None = Query(None, max_length=120, description="按问题、引用标题或域名搜索"),
    limit: int = Query(30, ge=1, le=50),
) -> dict:
    """内容版本可关联的「AI 回答来源」选项，一条 trace 一个选项。

    普通运营只需要选择一篇稿子针对的那条回答；前端再把该 trace 下的引用
    ID 一起提交，沿用现有版本关联接口，不新增第二套关联模型。
    """
    stmt = (
        select(
            MonitoringCitation,
            MonitoringSample,
            MonitoringTask,
            Question,
            QuestionVersion,
            AiEngine,
            AiEngineEntry,
        )
        .join(MonitoringSample, MonitoringSample.id == MonitoringCitation.sample_id)
        .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
        .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
        .join(Question, Question.id == QuestionVersion.question_id)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .where(MonitoringCitation.project_id == ctx.project.id)
        .where(
            func.coalesce(
                MonitoringCitation.trace_id,
                MonitoringSample.trace_id,
                MonitoringTask.trace_id,
            ).is_not(None)
        )
        .order_by(MonitoringCitation.created_at.desc(), MonitoringCitation.id)
        .limit(300)
    )
    term = (q or "").strip()
    if term:
        pattern = f"%{term}%"
        stmt = stmt.where(
            or_(
                Question.title.ilike(pattern),
                QuestionVersion.text.ilike(pattern),
                MonitoringSample.raw_answer.ilike(pattern),
                MonitoringCitation.title.ilike(pattern),
                MonitoringCitation.domain.ilike(pattern),
                AiEngine.name.ilike(pattern),
                AiEngineEntry.name.ilike(pattern),
            )
        )

    groups: dict[str, dict] = {}
    for citation, sample, task, question, question_version, engine, entry in db.execute(stmt):
        trace_id = citation.trace_id or sample.trace_id or task.trace_id
        if not trace_id:
            continue
        group = groups.get(trace_id)
        if group is None:
            group = {
                "trace_id": trace_id,
                "question_title": question.title,
                "question_text": question_version.text,
                "engine_name": engine.name,
                "entry_name": entry.name,
                "answer_excerpt": _answer_excerpt(sample.raw_answer),
                "sampled_at": sample.sampled_at or citation.created_at,
                "citation_ids": [],
                "domains": [],
            }
            groups[trace_id] = group
        group["citation_ids"].append(str(citation.id))
        if citation.domain and citation.domain not in group["domains"]:
            group["domains"].append(citation.domain)

    options = []
    for group in groups.values():
        group["citation_ids"] = list(dict.fromkeys(group["citation_ids"]))
        group["citation_count"] = len(group["citation_ids"])
        group["domains"] = group["domains"][:3]
        options.append(group)
        if len(options) >= limit:
            break
    return ok(options)


def _date_window(
    ctx: ProjectContext, start_date: date | None, end_date: date | None
) -> tuple[datetime | None, datetime | None]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise AppError("start_date 不能晚于 end_date", code="invalid_date_range")

    try:
        tz = ZoneInfo(ctx.project.timezone or "Asia/Shanghai")
    except Exception:
        tz = timezone.utc

    start_at = (
        datetime.combine(start_date, time.min, tzinfo=tz).astimezone(timezone.utc)
        if start_date is not None
        else None
    )
    end_at = (
        datetime.combine(end_date, time.max, tzinfo=tz).astimezone(timezone.utc)
        if end_date is not None
        else None
    )
    return start_at, end_at


def _citation_export_filters(
    project_id: uuid.UUID,
    *,
    engine_id: uuid.UUID | None,
    question_id: uuid.UUID | None,
    review_status: CitationReviewStatus | None,
    start_at: datetime | None,
    end_at: datetime | None,
) -> list:
    filters = [MonitoringCitation.project_id == project_id]
    if engine_id is not None:
        filters.append(AiEngine.id == engine_id)
    if question_id is not None:
        filters.append(Question.id == question_id)
    if review_status is not None:
        filters.append(MonitoringCitation.review_status == review_status)
    if start_at is not None:
        filters.append(MonitoringSample.sampled_at >= start_at)
    if end_at is not None:
        filters.append(MonitoringSample.sampled_at <= end_at)
    return filters


def _citation_export_statement(
    project_id: uuid.UUID,
    *,
    engine_id: uuid.UUID | None,
    question_id: uuid.UUID | None,
    review_status: CitationReviewStatus | None,
    start_at: datetime | None,
    end_at: datetime | None,
):
    return (
        select(
            MonitoringCitation,
            MonitoringSample.sampled_at,
            AiEngine.code.label("engine_code"),
            AiEngine.name.label("engine_name"),
            AiEngineEntry.name.label("entry_name"),
            Question.code.label("question_code"),
            Question.title.label("question_title"),
        )
        .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .join(AiEngine, AiEngineEntry.engine_id == AiEngine.id)
        .join(
            QuestionVersion,
            MonitoringTask.question_version_id == QuestionVersion.id,
        )
        .join(Question, QuestionVersion.question_id == Question.id)
        .where(
            *_citation_export_filters(
                project_id,
                engine_id=engine_id,
                question_id=question_id,
                review_status=review_status,
                start_at=start_at,
                end_at=end_at,
            )
        )
    )


def _citation_csv(rows) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "citation_id",
            "sampled_at",
            "engine_code",
            "engine_name",
            "entry_name",
            "question_code",
            "question_title",
            "raw_url",
            "normalized_url",
            "domain",
            "title",
            "source_category",
            "page_type",
            "review_status",
            "channel_id",
            "is_brand_related",
            "review_note",
        ]
    )
    for citation, sampled_at, engine_code, engine_name, entry_name, question_code, question_title in rows:
        writer.writerow(
            safe_csv_row(
                [
                    str(citation.id),
                    sampled_at.isoformat() if sampled_at else "",
                    engine_code,
                    engine_name,
                    entry_name,
                    question_code,
                    question_title,
                    citation.raw_url,
                    citation.normalized_url,
                    citation.domain,
                    citation.title,
                    citation.source_category.value if citation.source_category else "",
                    citation.page_type.value if citation.page_type else "",
                    citation.review_status.value,
                    str(citation.channel_id) if citation.channel_id else "",
                    "1" if citation.is_brand_related else "0",
                    citation.review_note,
                ]
            )
        )
    return buffer.getvalue()


@router.get("/source-reviews", response_model=PagedEnvelope[SourceReviewItem])
def list_source_reviews(
    ctx: ProjectContext = Depends(require_permission("channel.read")),
    db: Session = Depends(get_db),
    status: SourceReviewStatus | None = Query(None, description="pending / classified / ignored"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    """AI 引用中的未知域名队列；与发布渠道待归类队列分开。

    分页、计数与逐域名统计都在 `services/source_review_queue` 里算，这里只做包装。
    """
    total, rows, stats = page_source_reviews(
        db, ctx.project.id, status=status, page=page, page_size=page_size
    )
    return ok_page(
        [_source_review_payload(row, stats.get(row.domain)) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


def _source_review_payload(row: CitationSourceReview, stats) -> dict:
    return {
        "review_id": str(row.id),
        "domain": row.domain,
        "status": row.status.value,
        "source_category": row.source_category.value if row.source_category else None,
        "suggested_source_category": (
            row.suggested_source_category.value if row.suggested_source_category else None
        ),
        "classification_source": (
            row.classification_source.value if row.classification_source else None
        ),
        "rule_version": row.classification_rule_version,
        "citation_count": int(getattr(stats, "citation_count", 0) or 0),
        "sample_count": int(getattr(stats, "sample_count", 0) or 0),
        "last_sampled_at": getattr(stats, "last_sampled_at", None),
        "reviewed_at": row.reviewed_at,
        "review_note": row.review_note,
    }


@router.post(
    "/source-reviews/{review_id}/classify",
    response_model=Envelope[SourceReviewItem],
)
def classify_source_review(
    review_id: uuid.UUID,
    payload: CitationSourceClassifyRequest,
    ctx: ProjectContext = Depends(require_permission("evidence.review")),
    db: Session = Depends(get_db),
) -> dict:
    """人工定来源类别：写入审核项并回填同域引用，后续自动分类不得覆盖。"""
    review = require_scoped_row(
        db,
        CitationSourceReview,
        ctx.project.id,
        resource="source_review",
        for_update=True,
        id=review_id,
    )
    now = datetime.now(timezone.utc)
    review.status = ensure_source_review_transition(review.status, SourceReviewStatus.CLASSIFIED)
    review.source_category = payload.source_category
    review.classification_source = ClassificationSource.MANUAL
    review.classification_rule_version = CLASSIFIER_VERSION
    review.reviewed_by = ctx.user.id
    review.reviewed_at = now
    review.review_note = payload.review_note
    citations = db.scalars(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == ctx.project.id,
            MonitoringCitation.domain == review.domain,
        )
    ).all()
    for citation in citations:
        citation.source_category = payload.source_category
        citation.classification_source = ClassificationSource.MANUAL
        citation.classification_rule_version = CLASSIFIER_VERSION
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citation.source_classify",
        target_type="citation_source_review",
        target_id=review.id,
        payload={
            "domain": review.domain,
            "source_category": payload.source_category.value,
            "citations": len(citations),
        },
    )
    db.commit()
    return ok(_source_review_payload(review, None))


@router.post("/source-reviews/bulk-classify", response_model=Envelope[dict])
def bulk_classify_source_reviews(
    payload: CitationSourceBulkClassifyRequest,
    ctx: ProjectContext = Depends(require_permission("evidence.review")),
    db: Session = Depends(get_db),
) -> dict:
    """批量人工归类：一次最多 200 个域名，每个域名仍逐条回填引用并统一留痕。"""
    reviews = db.scalars(
        select(CitationSourceReview)
        .where(
            CitationSourceReview.project_id == ctx.project.id,
            CitationSourceReview.id.in_(payload.review_ids),
        )
        .with_for_update()
    ).all()
    if not reviews:
        raise ResourceMissingError("待归类域名不存在", code="source_review_missing")
    now = datetime.now(timezone.utc)
    domains = [review.domain for review in reviews]
    citations = db.scalars(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == ctx.project.id,
            MonitoringCitation.domain.in_(domains),
        )
    ).all()
    for review in reviews:
        review.status = ensure_source_review_transition(review.status, SourceReviewStatus.CLASSIFIED)
        review.source_category = payload.source_category
        review.classification_source = ClassificationSource.MANUAL
        review.classification_rule_version = CLASSIFIER_VERSION
        review.reviewed_by = ctx.user.id
        review.reviewed_at = now
        review.review_note = payload.review_note
    for citation in citations:
        citation.source_category = payload.source_category
        citation.classification_source = ClassificationSource.MANUAL
        citation.classification_rule_version = CLASSIFIER_VERSION
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citation.source_bulk_classify",
        target_type="citation_source_review",
        payload={
            "domains": domains,
            "source_category": payload.source_category.value,
            "reviews": len(reviews),
            "citations": len(citations),
            "skipped": len(set(payload.review_ids)) - len(reviews),
        },
    )
    db.commit()
    return ok(
        {
            "classified": len(reviews),
            "citations": len(citations),
            "skipped": len(set(payload.review_ids)) - len(reviews),
            "source_category": payload.source_category.value,
        }
    )


@router.post(
    "/source-reviews/{review_id}/ignore",
    response_model=Envelope[SourceReviewItem],
)
def ignore_source_review(
    review_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("evidence.review")),
    db: Session = Depends(get_db),
) -> dict:
    """忽略一个未知来源；引用仍保留，只是不再提示审核。"""
    review = require_scoped_row(
        db,
        CitationSourceReview,
        ctx.project.id,
        resource="source_review",
        for_update=True,
        id=review_id,
    )
    review.status = ensure_source_review_transition(review.status, SourceReviewStatus.IGNORED)
    review.reviewed_by = ctx.user.id
    review.reviewed_at = datetime.now(timezone.utc)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citation.source_ignore",
        target_type="citation_source_review",
        target_id=review.id,
        payload={"domain": review.domain},
    )
    db.commit()
    return ok(_source_review_payload(review, None))


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


@router.get(
    "/export",
    responses={
        200: {
            "description": "引用明细 CSV（按引擎/问题/采样时间筛选，写审计；超上限返回 400）",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    },
)
def export_citations(
    ctx: ProjectContext = Depends(require_permission("export.data")),
    db: Session = Depends(get_db),
    engine_id: uuid.UUID | None = Query(None, description="按 AI 引擎 ID（ai_engines.id）筛选"),
    question_id: uuid.UUID | None = Query(None, description="按问题 ID（questions.id）筛选"),
    start_date: date | None = Query(None, description="采样日期起（含），按项目时区解析"),
    end_date: date | None = Query(None, description="采样日期止（含），按项目时区解析"),
    review_status: CitationReviewStatus | None = Query(
        None, description="按引用复核状态筛选"
    ),
) -> Response:
    """引用明细同步导出；标题/URL 原样输出，文件名带项目与时间戳。"""
    start_at, end_at = _date_window(ctx, start_date, end_date)
    statement = _citation_export_statement(
        ctx.project.id,
        engine_id=engine_id,
        question_id=question_id,
        review_status=review_status,
        start_at=start_at,
        end_at=end_at,
    )
    row_count = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    ensure_sync_export_allowed(row_count, what="引用明细")

    rows = db.execute(
        statement.order_by(MonitoringSample.sampled_at.desc())
    ).all()
    content = _citation_csv(rows)

    filters: dict[str, object] = {"resource": "citations"}
    if engine_id is not None:
        filters["engine_id"] = str(engine_id)
    if question_id is not None:
        filters["question_id"] = str(question_id)
    if start_date is not None:
        filters["start_date"] = start_date.isoformat()
    if end_date is not None:
        filters["end_date"] = end_date.isoformat()
    if review_status is not None:
        filters["review_status"] = review_status.value

    record_export(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        export_type="citations",
        row_count=len(rows),
        filters=filters,
        mode="sync",
    )
    db.commit()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"citations-{ctx.project.code}-{stamp}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )



@router.patch("/{citation_id}/page-type", response_model=Envelope[CitationData])
def override_citation_page_type(
    citation_id: uuid.UUID,
    payload: CitationPageTypeRequest,
    ctx: ProjectContext = Depends(require_permission("evidence.review")),
    db: Session = Depends(get_db),
) -> dict:
    """人工覆盖单条引用的页面类型，并标记为 manual，后续自动分类不再覆盖。

    页面类型按引用记录，不做域名级批量覆盖；来源类别仍由 source-reviews 队列处理。
    """
    row = require_scoped_row(
        db,
        MonitoringCitation,
        ctx.project.id,
        resource="monitoring_citation",
        id=citation_id,
        for_update=True,
    )
    page_type_from = row.page_type.value if row.page_type else None
    row.page_type = payload.page_type
    row.classification_source = ClassificationSource.MANUAL
    row.classification_rule_version = "manual-page-type-v1"
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="citation.page_type_override",
        target_type="monitoring_citation",
        target_id=row.id,
        payload={
            "page_type_from": page_type_from,
            "page_type_to": payload.page_type.value,
            "classification_source": ClassificationSource.MANUAL.value,
            "classification_rule_version": row.classification_rule_version,
        },
    )
    db.commit()
    return ok(_citation_payload(row))


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
    # 品牌相关是自动判定字段，人工复核允许显式覆盖；不传保持原判，避免误清空。
    if "is_brand_related" in payload.model_fields_set:
        if payload.is_brand_related is None:
            raise AppError(
                "is_brand_related 只能显式设为 true 或 false",
                code="invalid_brand_flag",
            )
        row.is_brand_related = payload.is_brand_related
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
            ensure_channel_approved(channel)
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
            "is_brand_related": row.is_brand_related,
        },
    )
    db.commit()
    return ok(_citation_payload(row))

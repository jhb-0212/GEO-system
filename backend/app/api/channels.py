"""渠道台账与导出：导出必须走 export.data 能力，并且一定写审计。

导出两种模式：

- 不带筛选参数：沿用原有行为，导出本项目全部渠道台账（5 列）。
- 带 `engine_id` / `question_id` / `start_date` / `end_date` 任一参数：按引用联表
  `monitoring_citations → monitoring_samples → monitoring_tasks → ai_engine_entries →
  ai_engines / questions` 聚合，输出“渠道列表 + 覆盖情况”，一个渠道一行。
  渠道按 `channel_id` 去重，页面数按 `normalized_url` 去重，与看板口径一致。
  审计 `filters` 会记录实际筛选条件，便于复跑。
"""

import csv
import io
import uuid
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    ChannelData,
    ChannelDetailData,
    Envelope,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import AppError, ResourceMissingError
from app.db.session import get_db
from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.services.audit import record_export

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/channels",
    tags=["渠道"],
    responses=COMMON_ERRORS,
)

CSV_COLUMNS = ("code", "name", "category", "status", "primary_domain")
FILTERED_CSV_COLUMNS = CSV_COLUMNS + (
    "citation_count",
    "sample_count",
    "page_count",
    "engine_codes",
    "engine_names",
    "question_codes",
    "first_sampled_at",
    "last_sampled_at",
)


@router.get("", response_model=PagedEnvelope[ChannelData])
def list_channels(
    ctx: ProjectContext = Depends(require_permission("channel.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    total = (
        db.scalar(
            select(func.count()).select_from(Channel).where(Channel.project_id == ctx.project.id)
        )
        or 0
    )
    rows = db.scalars(
        select(Channel)
        .where(Channel.project_id == ctx.project.id)
        .order_by(Channel.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "category": row.category,
                "status": row.status,
                "primary_domain": row.primary_domain,
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


def _channel_csv(rows: list[Channel]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            [row.code, row.name, row.category, row.status, row.primary_domain or ""]
        )
    return buffer.getvalue()


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


def _filtered_channel_rows(
    ctx: ProjectContext,
    db: Session,
    *,
    engine_id: uuid.UUID | None,
    question_id: uuid.UUID | None,
    start_at: datetime | None,
    end_at: datetime | None,
) -> list[dict]:
    """按引用联表聚合渠道，一个 channel_id 一行；同渠道多次引用不重复出行。"""
    stmt = (
        select(
            Channel,
            MonitoringCitation.id,
            MonitoringCitation.sample_id,
            MonitoringCitation.normalized_url,
            MonitoringSample.sampled_at,
            AiEngine.code,
            AiEngine.name,
            Question.code,
        )
        .select_from(Channel)
        .join(MonitoringCitation, MonitoringCitation.channel_id == Channel.id)
        .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(Question, QuestionVersion.question_id == Question.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .join(AiEngine, AiEngineEntry.engine_id == AiEngine.id)
        .where(
            Channel.project_id == ctx.project.id,
            MonitoringCitation.project_id == ctx.project.id,
            MonitoringSample.project_id == ctx.project.id,
            MonitoringTask.project_id == ctx.project.id,
            Question.project_id == ctx.project.id,
        )
        .order_by(Channel.code, MonitoringSample.sampled_at)
    )
    if engine_id is not None:
        stmt = stmt.where(AiEngineEntry.engine_id == engine_id)
    if question_id is not None:
        stmt = stmt.where(Question.id == question_id)
    if start_at is not None:
        stmt = stmt.where(MonitoringSample.sampled_at >= start_at)
    if end_at is not None:
        stmt = stmt.where(MonitoringSample.sampled_at <= end_at)

    grouped: dict[uuid.UUID, dict] = {}
    for (
        channel,
        citation_id,
        sample_id,
        normalized_url,
        sampled_at,
        engine_code,
        engine_name,
        question_code,
    ) in db.execute(stmt).all():
        item = grouped.setdefault(
            channel.id,
            {
                "channel": channel,
                "citation_count": 0,
                "sample_ids": set(),
                "page_urls": set(),
                "engine_codes": set(),
                "engine_names": set(),
                "question_codes": set(),
                "first_sampled_at": None,
                "last_sampled_at": None,
            },
        )
        item["citation_count"] += 1
        item["sample_ids"].add(sample_id)
        if normalized_url:
            item["page_urls"].add(normalized_url)
        item["engine_codes"].add(engine_code)
        item["engine_names"].add(engine_name)
        item["question_codes"].add(question_code)
        if sampled_at is not None:
            if item["first_sampled_at"] is None or sampled_at < item["first_sampled_at"]:
                item["first_sampled_at"] = sampled_at
            if item["last_sampled_at"] is None or sampled_at > item["last_sampled_at"]:
                item["last_sampled_at"] = sampled_at

    rows = []
    for item in grouped.values():
        channel = item["channel"]
        rows.append(
            {
                "code": channel.code,
                "name": channel.name,
                "category": channel.category,
                "status": channel.status,
                "primary_domain": channel.primary_domain or "",
                "citation_count": item["citation_count"],
                "sample_count": len(item["sample_ids"]),
                "page_count": len(item["page_urls"]),
                "engine_codes": "|".join(sorted(item["engine_codes"])),
                "engine_names": "|".join(sorted(item["engine_names"])),
                "question_codes": "|".join(sorted(item["question_codes"])),
                "first_sampled_at": (
                    item["first_sampled_at"].isoformat() if item["first_sampled_at"] else ""
                ),
                "last_sampled_at": (
                    item["last_sampled_at"].isoformat() if item["last_sampled_at"] else ""
                ),
            }
        )
    return rows


def _filtered_channel_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(FILTERED_CSV_COLUMNS)
    for row in rows:
        writer.writerow([row[column] for column in FILTERED_CSV_COLUMNS])
    return buffer.getvalue()


@router.get(
    "/export",
    responses={
        200: {
            "description": "CSV 导出（写审计；超过行数上限返回 409）",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    },
)
def export_channels(
    ctx: ProjectContext = Depends(require_permission("export.data")),
    db: Session = Depends(get_db),
    engine_id: uuid.UUID | None = Query(
        None, description="按 AI 引擎 ID（ai_engines.id）筛选，需联表到监测任务与引用"
    ),
    question_id: uuid.UUID | None = Query(
        None, description="按问题 ID（questions.id）筛选，需联表到问题版本与监测任务"
    ),
    start_date: date | None = Query(None, description="采样日期起（含），按项目时区解析"),
    end_date: date | None = Query(None, description="采样日期止（含），按项目时区解析"),
) -> Response:
    """同步 CSV 导出：超过 export_sync_row_limit 由 record_export 抛错，要求改异步。

    无筛选参数时导出全量渠道台账；带任一筛选参数时输出按引用聚合的渠道覆盖列表。
    """
    has_filter = any(
        value is not None for value in (engine_id, question_id, start_date, end_date)
    )
    filters: dict[str, object] = {"resource": "channels"}

    if has_filter:
        start_at, end_at = _date_window(ctx, start_date, end_date)
        rows = _filtered_channel_rows(
            ctx,
            db,
            engine_id=engine_id,
            question_id=question_id,
            start_at=start_at,
            end_at=end_at,
        )
        content = _filtered_channel_csv(rows)
        if engine_id is not None:
            filters["engine_id"] = str(engine_id)
        if question_id is not None:
            filters["question_id"] = str(question_id)
        if start_date is not None:
            filters["start_date"] = start_date.isoformat()
        if end_date is not None:
            filters["end_date"] = end_date.isoformat()
    else:
        rows = db.scalars(
            select(Channel).where(Channel.project_id == ctx.project.id).order_by(Channel.code)
        ).all()
        content = _channel_csv(rows)

    record_export(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        export_type="channels",
        row_count=len(rows),
        filters=filters,
        mode="sync",
    )
    db.commit()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"channels-{ctx.project.code}-{stamp}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _answer_excerpt(value: str | None, limit: int = 200) -> str | None:
    """返回可展示的回答摘要；完整回答留在 samples 表，不在明细接口里放大传输。"""
    if not value:
        return None
    text = " ".join(value.split())
    return text if len(text) <= limit else f"{text[:limit]}..."


@router.get(
    "/{channel_id}",
    response_model=Envelope[ChannelDetailData],
    responses={404: COMMON_ERRORS[404]},
)
def get_channel_detail(
    channel_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("channel.read")),
    db: Session = Depends(get_db),
) -> dict:
    """渠道详情：台账字段 + 引用覆盖摘要 + 逐条引用，用于从渠道数点开明细。"""
    channel = db.scalar(
        select(Channel).where(
            Channel.id == channel_id,
            Channel.project_id == ctx.project.id,
        )
    )
    if channel is None:
        raise ResourceMissingError("渠道不存在")

    rows = db.execute(
        select(
            MonitoringCitation.id,
            MonitoringCitation.sample_id,
            MonitoringCitation.raw_url,
            MonitoringCitation.normalized_url,
            MonitoringCitation.domain,
            MonitoringCitation.is_brand_related,
            MonitoringCitation.review_status,
            MonitoringSample.status,
            MonitoringSample.sampled_at,
            MonitoringSample.brand_mentioned,
            MonitoringSample.failure_code,
            MonitoringSample.raw_answer,
            MonitoringTask.id,
            AiEngine.code,
            AiEngine.name,
            Question.code,
        )
        .select_from(MonitoringCitation)
        .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(Question, QuestionVersion.question_id == Question.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .join(AiEngine, AiEngineEntry.engine_id == AiEngine.id)
        .where(
            MonitoringCitation.channel_id == channel.id,
            MonitoringCitation.project_id == ctx.project.id,
            MonitoringSample.project_id == ctx.project.id,
            MonitoringTask.project_id == ctx.project.id,
            Question.project_id == ctx.project.id,
        )
        .order_by(MonitoringSample.sampled_at.desc().nullslast(), MonitoringCitation.id)
    ).all()

    page_urls: set[str] = set()
    sample_ids: set[uuid.UUID] = set()
    engine_codes: set[str] = set()
    question_codes: set[str] = set()
    first_sampled_at: datetime | None = None
    last_sampled_at: datetime | None = None
    citations: list[dict] = []

    for row in rows:
        (
            citation_id,
            sample_id,
            raw_url,
            normalized_url,
            domain,
            is_brand_related,
            review_status,
            sample_status,
            sampled_at,
            brand_mentioned,
            failure_code,
            raw_answer,
            task_id,
            engine_code,
            engine_name,
            question_code,
        ) = row

        sample_ids.add(sample_id)
        engine_codes.add(engine_code)
        question_codes.add(question_code)
        if normalized_url:
            page_urls.add(normalized_url)
        if sampled_at is not None:
            if first_sampled_at is None or sampled_at < first_sampled_at:
                first_sampled_at = sampled_at
            if last_sampled_at is None or sampled_at > last_sampled_at:
                last_sampled_at = sampled_at

        citations.append(
            {
                "citation_id": str(citation_id),
                "sample_id": str(sample_id),
                "task_id": str(task_id),
                "engine_code": engine_code,
                "engine_name": engine_name,
                "question_code": question_code,
                "sample_status": str(sample_status),
                "sampled_at": sampled_at,
                "raw_url": raw_url,
                "normalized_url": normalized_url,
                "domain": domain,
                "is_brand_related": is_brand_related,
                "review_status": str(review_status),
                "brand_mentioned": brand_mentioned,
                "failure_code": str(failure_code) if failure_code else None,
                "answer_excerpt": _answer_excerpt(raw_answer),
            }
        )

    return ok(
        {
            "id": str(channel.id),
            "code": channel.code,
            "name": channel.name,
            "category": channel.category,
            "status": channel.status,
            "primary_domain": channel.primary_domain,
            "citation_count": len(citations),
            "sample_count": len(sample_ids),
            "page_count": len(page_urls),
            "page_urls": sorted(page_urls),
            "engine_codes": sorted(engine_codes),
            "question_codes": sorted(question_codes),
            "first_sampled_at": first_sampled_at,
            "last_sampled_at": last_sampled_at,
            "citations": citations,
        }
    )

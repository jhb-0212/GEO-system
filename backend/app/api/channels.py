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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    ChannelAnomalyListData,
    ChannelData,
    ChannelDetailData,
    ChannelEditableData,
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
    ChannelAlias,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.schemas import ChannelCreate, ChannelUpdate
from app.services.audit import record_audit, record_export
from app.services.channel_anomalies import detect_channel_anomalies
from app.services.csv_safety import safe_csv_row
from app.services.export_guard import ensure_sync_export_allowed
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/channels",
    tags=["渠道"],
    responses=COMMON_ERRORS,
)

CSV_COLUMNS = ("code", "name", "category", "status", "primary_domain", "owner_name", "owner_contact")
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


def _channel_data(channel: Channel) -> dict:
    return {
        "id": str(channel.id),
        "code": channel.code,
        "name": channel.name,
        "category": str(channel.category),
        "status": str(channel.status),
        "primary_domain": channel.primary_domain,
        "publish_url": channel.publish_url,
        "login_url": channel.login_url,
        "owner_name": channel.owner_name,
        "owner_contact": channel.owner_contact,
    }


def _channel_edit_data(db: Session, channel: Channel) -> dict:
    aliases = db.scalars(
        select(ChannelAlias)
        .where(
            ChannelAlias.project_id == channel.project_id,
            ChannelAlias.channel_id == channel.id,
        )
        .order_by(ChannelAlias.domain)
    ).all()
    return {
        **_channel_data(channel),
        "notes": channel.notes,
        "is_active": channel.is_active,
        "aliases": [
            {"domain": alias.domain, "alias_name": alias.alias_name}
            for alias in aliases
        ],
    }


def _ensure_primary_domain(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel: Channel | None,
    domain: str | None,
) -> None:
    """主域名同样要全局唯一：不能占用其他渠道的主域名或别名。"""
    if domain is None:
        return
    channel_filters = [
        Channel.project_id == project_id,
        Channel.primary_domain == domain,
    ]
    alias_filters = [
        ChannelAlias.project_id == project_id,
        ChannelAlias.domain == domain,
    ]
    if channel is not None:
        channel_filters.append(Channel.id != channel.id)
        alias_filters.append(ChannelAlias.channel_id != channel.id)
    if db.scalar(select(Channel).where(*channel_filters)) is not None:
        raise AppError("域名已作为其他渠道主域名", code="channel_domain_conflict")
    if db.scalar(select(ChannelAlias).where(*alias_filters)) is not None:
        raise AppError("域名已归属其他渠道", code="channel_domain_conflict")


def _ensure_alias(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel: Channel,
    domain: str | None,
    alias_name: str | None,
) -> None:
    """旧域名/旧名称落别名；域名归属别的渠道时拒绝，避免静默覆盖。"""
    if domain is None:
        return
    other_channel = db.scalar(
        select(Channel).where(
            Channel.project_id == project_id,
            Channel.primary_domain == domain,
            Channel.id != channel.id,
        )
    )
    if other_channel is not None:
        raise AppError("域名已作为其他渠道主域名", code="channel_domain_conflict")
    existing = db.scalar(
        select(ChannelAlias).where(
            ChannelAlias.project_id == project_id,
            ChannelAlias.domain == domain,
        )
    )
    if existing is not None:
        if existing.channel_id != channel.id:
            raise AppError("域名已归属其他渠道", code="channel_domain_conflict")
        if alias_name:
            existing.alias_name = alias_name
        return
    db.add(
        ChannelAlias(
            project_id=project_id,
            channel_id=channel.id,
            domain=domain,
            alias_name=alias_name,
        )
    )


def _preserve_old_identity(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel: Channel,
    old_name: str,
    old_domain: str | None,
) -> None:
    """改名/换主域名时保留旧名称；有旧域名就落 ChannelAlias，没有就写备注。"""
    if old_domain:
        _ensure_alias(
            db,
            project_id=project_id,
            channel=channel,
            domain=old_domain,
            alias_name=old_name,
        )
        return
    marker = f"曾用名：{old_name}"
    if marker not in (channel.notes or ""):
        channel.notes = f"{channel.notes}\n{marker}" if channel.notes else marker


def _add_aliases(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel: Channel,
    aliases: list[str],
) -> None:
    for domain in aliases:
        if domain == channel.primary_domain:
            continue
        _ensure_alias(
            db,
            project_id=project_id,
            channel=channel,
            domain=domain,
            alias_name=channel.name,
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
                "publish_url": row.publish_url,
                "login_url": row.login_url,
                "owner_name": row.owner_name,
                "owner_contact": row.owner_contact,
            }
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[ChannelEditableData])
def create_channel(
    payload: ChannelCreate,
    ctx: ProjectContext = Depends(require_permission("channel.write")),
    db: Session = Depends(get_db),
) -> dict:
    """新增渠道台账；code 项目内唯一，旧域名可同时写入别名。"""
    existing = db.scalar(
        select(Channel).where(
            Channel.project_id == ctx.project.id,
            Channel.code == payload.code,
        )
    )
    if existing is not None:
        raise AppError("渠道 code 已存在", code="channel_code_conflict")
    _ensure_primary_domain(
        db,
        project_id=ctx.project.id,
        channel=None,
        domain=payload.primary_domain,
    )

    channel = Channel(
        project_id=ctx.project.id,
        code=payload.code,
        name=payload.name,
        category=payload.category,
        status=payload.status,
        primary_domain=payload.primary_domain,
        publish_url=payload.publish_url,
        login_url=payload.login_url,
        owner_name=payload.owner_name,
        owner_contact=payload.owner_contact,
        notes=payload.notes,
        is_active=payload.is_active,
    )
    db.add(channel)
    try:
        db.flush()
        _add_aliases(
            db,
            project_id=ctx.project.id,
            channel=channel,
            aliases=payload.aliases,
        )
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("渠道 code 或域名已存在", code="channel_conflict") from exc
    except AppError:
        db.rollback()
        raise

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="channel.create",
        target_type="channel",
        target_id=channel.id,
        payload={
            "code": channel.code,
            "category": str(channel.category),
            "status": str(channel.status),
            "primary_domain": channel.primary_domain,
        },
    )
    db.commit()
    return ok(_channel_edit_data(db, channel))


@router.patch("/{channel_id}", response_model=Envelope[ChannelEditableData])
def update_channel(
    channel_id: uuid.UUID,
    payload: ChannelUpdate,
    ctx: ProjectContext = Depends(require_permission("channel.write")),
    db: Session = Depends(get_db),
) -> dict:
    """局部更新渠道：分类/状态/主域名可改，code 不改；旧名称和旧域名保留。"""
    channel = require_scoped_row(
        db,
        Channel,
        ctx.project.id,
        resource="channel",
        for_update=True,
        id=channel_id,
    )
    changes = payload.model_dump(exclude_unset=True)
    aliases = changes.pop("aliases", None)

    for field in ("name", "category", "status", "is_active"):
        if field in changes and changes[field] is None:
            raise AppError(f"{field} 不能为空", code="invalid_channel_field")

    old_name = channel.name
    old_domain = channel.primary_domain
    name_changed = changes.get("name") != old_name if "name" in changes else False
    domain_changed = (
        changes.get("primary_domain") != old_domain
        if "primary_domain" in changes
        else False
    )
    if domain_changed:
        _ensure_primary_domain(
            db,
            project_id=ctx.project.id,
            channel=channel,
            domain=changes.get("primary_domain"),
        )
    try:
        if name_changed or domain_changed:
            _preserve_old_identity(
                db,
                project_id=ctx.project.id,
                channel=channel,
                old_name=old_name,
                old_domain=old_domain,
            )

        for field, value in changes.items():
            setattr(channel, field, value)
        if aliases:
            _add_aliases(
                db,
                project_id=ctx.project.id,
                channel=channel,
                aliases=aliases,
            )

        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("渠道 code 或域名已存在", code="channel_conflict") from exc
    except AppError:
        db.rollback()
        raise

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="channel.update",
        target_type="channel",
        target_id=channel.id,
        payload={
            "changed_fields": sorted(changes.keys()),
            "aliases": aliases or [],
            "code": channel.code,
            "category": str(channel.category),
            "status": str(channel.status),
            "primary_domain": channel.primary_domain,
        },
    )
    db.commit()
    return ok(_channel_edit_data(db, channel))


def _channel_csv(rows: list[Channel]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            safe_csv_row([
                row.code,
                row.name,
                row.category,
                row.status,
                row.primary_domain or "",
                row.owner_name or "",
                row.owner_contact or "",
            ])
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


def _filtered_channel_statement(
    ctx: ProjectContext,
    *,
    engine_id: uuid.UUID | None,
    question_id: uuid.UUID | None,
    start_at: datetime | None,
    end_at: datetime | None,
):
    """筛选导出的联表语句；复用给「先计数、再取数」的上限校验。"""
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
    return stmt


def _filtered_channel_rows(
    ctx: ProjectContext,
    db: Session,
    *,
    engine_id: uuid.UUID | None,
    question_id: uuid.UUID | None,
    start_at: datetime | None,
    end_at: datetime | None,
    statement=None,
) -> list[dict]:
    """按引用联表聚合渠道，一个 channel_id 一行；同渠道多次引用不重复出行。"""
    stmt = statement if statement is not None else _filtered_channel_statement(
        ctx,
        engine_id=engine_id,
        question_id=question_id,
        start_at=start_at,
        end_at=end_at,
    )

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
                "owner_name": channel.owner_name or "",
                "owner_contact": channel.owner_contact or "",
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
        writer.writerow(safe_csv_row([row[column] for column in FILTERED_CSV_COLUMNS]))
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
        statement = _filtered_channel_statement(
            ctx,
            engine_id=engine_id,
            question_id=question_id,
            start_at=start_at,
            end_at=end_at,
        )
        # 导出的行是渠道，但真实扫描量是引用行：先按引用行数卡同步上限，
        # 否则大项目会在 record_export 之前就把整张引用表读进内存。
        citation_row_count = (
            db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        ensure_sync_export_allowed(citation_row_count, what="筛选导出需扫描的引用")
        rows = _filtered_channel_rows(
            ctx,
            db,
            engine_id=engine_id,
            question_id=question_id,
            start_at=start_at,
            end_at=end_at,
            statement=statement,
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


@router.get("/anomalies", response_model=Envelope[ChannelAnomalyListData])
def get_channel_anomalies(
    ctx: ProjectContext = Depends(require_permission("channel.read")),
    db: Session = Depends(get_db),
) -> dict:
    """渠道台账与发布回执的一致性异常清单，供台账顶部提示和逐条处理。"""
    return ok(detect_channel_anomalies(db, ctx.project.id))


def _channel_citation_statement(channel_id: uuid.UUID, project_id: uuid.UUID):
    """渠道引用明细的基础联表语句；调用方只改列、排序与分页。"""
    return (
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
            MonitoringCitation.channel_id == channel_id,
            MonitoringCitation.project_id == project_id,
            MonitoringSample.project_id == project_id,
            MonitoringTask.project_id == project_id,
            Question.project_id == project_id,
        )
    )


@router.get(
    "/{channel_id}",
    response_model=Envelope[ChannelDetailData],
    responses={404: COMMON_ERRORS[404]},
)
def get_channel_detail(
    channel_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("channel.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="引用页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页引用条数，上限 100"),
) -> dict:
    """渠道详情：台账字段 + 引用覆盖摘要 + 分页后的逐条引用。"""
    channel = db.scalar(
        select(Channel).where(
            Channel.id == channel_id,
            Channel.project_id == ctx.project.id,
        )
    )
    if channel is None:
        raise ResourceMissingError("渠道不存在")

    base = _channel_citation_statement(channel.id, ctx.project.id)
    summary = db.execute(
        base.with_only_columns(
            func.count().label("citation_count"),
            func.count(func.distinct(MonitoringCitation.sample_id)).label("sample_count"),
            func.count(func.distinct(MonitoringCitation.normalized_url)).label("page_count"),
            func.min(MonitoringSample.sampled_at).label("first_sampled_at"),
            func.max(MonitoringSample.sampled_at).label("last_sampled_at"),
        )
    ).one()

    # 页面 / 引擎 / 题目只取去重后的有限集合，不跟着引用行数放大
    page_urls = [
        url
        for url in db.scalars(
            base.with_only_columns(MonitoringCitation.normalized_url)
            .where(MonitoringCitation.normalized_url.is_not(None))
            .distinct()
            .limit(500)
        ).all()
        if url
    ]
    code_rows = db.execute(
        base.with_only_columns(AiEngine.code, Question.code).distinct()
    ).all()
    engine_codes = sorted({row[0] for row in code_rows})
    question_codes = sorted({row[1] for row in code_rows})

    rows = db.execute(
        base.order_by(
            MonitoringSample.sampled_at.desc().nullslast(), MonitoringCitation.id
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

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
            **_channel_edit_data(db, channel),
            "citation_count": int(summary.citation_count or 0),
            "sample_count": int(summary.sample_count or 0),
            "page_count": int(summary.page_count or 0),
            "citation_page": page,
            "citation_page_size": page_size,
            "page_urls": sorted(page_urls),
            "engine_codes": engine_codes,
            "question_codes": question_codes,
            "first_sampled_at": summary.first_sampled_at,
            "last_sampled_at": summary.last_sampled_at,
            "citations": citations,
        }
    )

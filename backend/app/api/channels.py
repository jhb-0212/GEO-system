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
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    ChannelAnomalyListData,
    ChannelApprovalListData,
    ChannelData,
    ChannelDetailData,
    ChannelEditableData,
    Envelope,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import AppError, BusinessValidationError, ConflictError
from app.db.session import get_db
from app.models import Channel, ChannelApproval
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    CitationReviewStatus,
    ReviewDecision,
)
from app.schemas import ChannelCreate, ChannelDeleted, ChannelReviewRequest, ChannelUpdate
from app.services.state_machine import ensure_channel_approval_transition
from app.services.audit import record_audit, record_export
from app.services.channel_anomalies import detect_channel_anomalies
from app.services.channel_export import (
    filtered_csv as _filtered_channel_csv,
    filtered_rows as _filtered_channel_rows,
    filtered_statement as _filtered_channel_statement,
)
from app.services.channel_registry import (
    add_aliases as _add_aliases,
    all_channels as _all_channels,
    approval_history as _approval_history,
    channel_by_code as _channel_by_code,
    channel_detail_row as _channel_detail_row,
    channel_payload as _channel_data,
    delete_snapshot as _channel_delete_snapshot,
    edit_payload as _channel_edit_data,
    ensure_primary_domain as _ensure_primary_domain,
    page_channels as _page_channels,
    preserve_old_identity as _preserve_old_identity,
    count_rows as _count_rows,
    latest_approval as _latest_approval,
    reference_counts as _channel_reference_counts,
)
from app.services.channel_citations import (
    channel_citation_statement as _channel_citation_statement,
    channel_domains as _channel_domains,
    digest,
    observed_statement as _channel_observed_statement,
)
from app.services.csv_safety import safe_csv_row
from app.services.export_guard import ensure_sync_export_allowed
from app.services.project_scope import require_scoped_row
from app.services.time_windows import (
    ProjectTimezoneInvalid,
    local_day_start_utc,
    project_timezone,
)

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


@router.get("", response_model=PagedEnvelope[ChannelData])
def list_channels(
    ctx: ProjectContext = Depends(require_permission("channel.read")),
    db: Session = Depends(get_db),
    scope: Literal["publish", "monitoring"] | None = Query(
        None, description="publish=内容发布渠道；monitoring=监测/观察渠道"
    ),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    filters = [Channel.project_id == ctx.project.id]
    if scope == "publish":
        filters.append(Channel.category == ChannelCategory.CONTENT_PLATFORM)
    elif scope == "monitoring":
        filters.append(Channel.category != ChannelCategory.CONTENT_PLATFORM)
    rows, total = _page_channels(db, filters, page=page, page_size=page_size)
    return ok_page(
        [_channel_data(row) for row in rows],
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
    existing = _channel_by_code(db, ctx.project.id, payload.code)
    if existing is not None:
        raise AppError("渠道 code 已存在", code="channel_code_conflict")
    _ensure_primary_domain(
        db,
        project_id=ctx.project.id,
        channel=None,
        domain=payload.primary_domain,
    )

    now = datetime.now(timezone.utc)
    channel = Channel(
        project_id=ctx.project.id,
        code=payload.code,
        name=payload.name,
        category=payload.category,
        status=payload.status,
        approval_status=ChannelApprovalStatus.PENDING_REVIEW,
        submitted_by=ctx.user.id,
        submitted_at=now,
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
        db.add(
            ChannelApproval(
                project_id=ctx.project.id,
                channel_id=channel.id,
                submitted_by=ctx.user.id,
                submitted_at=now,
            )
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


@router.delete("/{channel_id}", response_model=Envelope[ChannelDeleted])
def delete_channel(
    channel_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("channel.write")),
    db: Session = Depends(get_db),
) -> dict:
    """受限删除误建渠道：只允许候选且无业务引用的记录。

    正常下线应停用（is_active=false）。准入审批不代表已投入使用，候选渠道即使
    审批通过，只要没有发布、引用、内容、线索或授权关联仍可删除；任何业务引用
    都会阻断删除，避免统计口径和追踪链被物理删除。
    """
    channel = require_scoped_row(
        db,
        Channel,
        ctx.project.id,
        resource="channel",
        for_update=True,
        id=channel_id,
    )
    if channel.status != ChannelStatus.CANDIDATE:
        raise ConflictError(
            "只有候选状态的渠道可以删除；已观测或已发布的渠道请改为停用。",
            code="channel_not_deletable",
        )

    references = _channel_reference_counts(db, ctx.project.id, channel.id)
    if references:
        detail = "、".join(f"{label} {count} 条" for label, count in references.items())
        raise ConflictError(
            f"该渠道仍有{detail}关联，不能删除；请改为停用。",
            code="channel_in_use",
        )

    snapshot = _channel_delete_snapshot(db, channel)
    channel_name = channel.name
    db.delete(channel)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "该渠道仍被其他数据引用，不能删除；请改为停用。",
            code="channel_in_use",
        ) from exc

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="channel.delete",
        target_type="channel",
        target_id=channel_id,
        payload={"channel": snapshot},
    )
    db.commit()
    return ok({"id": str(channel_id), "deleted": True, "name": channel_name})


@router.post("/{channel_id}/submit", response_model=Envelope[ChannelEditableData])
def resubmit_channel(
    channel_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("channel.write")),
    db: Session = Depends(get_db),
) -> dict:
    """驳回后重新提交准入审批：仅已驳回渠道可重新提交，回到待审核并追加新周期。"""
    channel = require_scoped_row(
        db,
        Channel,
        ctx.project.id,
        resource="channel",
        for_update=True,
        id=channel_id,
    )
    if channel.approval_status != ChannelApprovalStatus.REJECTED:
        raise AppError("只有已驳回的渠道可以重新提交", code="channel_resubmit_not_allowed")

    now = datetime.now(timezone.utc)
    channel.approval_status = ensure_channel_approval_transition(
        channel.approval_status, ChannelApprovalStatus.PENDING_REVIEW
    )
    channel.submitted_by = ctx.user.id
    channel.submitted_at = now
    channel.reviewed_by = None
    channel.reviewed_at = None
    channel.decision_comment = None
    db.add(
        ChannelApproval(
            project_id=ctx.project.id,
            channel_id=channel.id,
            submitted_by=ctx.user.id,
            submitted_at=now,
        )
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="channel.resubmit",
        target_type="channel",
        target_id=channel.id,
        payload={"code": channel.code},
    )
    db.commit()
    return ok(_channel_edit_data(db, channel))


@router.post("/{channel_id}/review", response_model=Envelope[ChannelEditableData])
def review_channel(
    channel_id: uuid.UUID,
    payload: ChannelReviewRequest,
    ctx: ProjectContext = Depends(require_permission("channel.approve")),
    db: Session = Depends(get_db),
) -> dict:
    """项目管理员审批准入：通过 / 驳回；驳回必须填写意见，仅待审核渠道可审。"""
    channel = require_scoped_row(
        db,
        Channel,
        ctx.project.id,
        resource="channel",
        for_update=True,
        id=channel_id,
    )
    if channel.approval_status != ChannelApprovalStatus.PENDING_REVIEW:
        raise AppError("该渠道已审批，不能重复审批", code="channel_already_reviewed")

    comment = (payload.comment or "").strip() or None
    if payload.decision == ReviewDecision.REJECTED and not comment:
        raise AppError("驳回渠道必须填写原因", code="channel_reject_comment_required")

    approved = payload.decision == ReviewDecision.APPROVED
    now = datetime.now(timezone.utc)
    channel.approval_status = ensure_channel_approval_transition(
        channel.approval_status,
        ChannelApprovalStatus.APPROVED
        if approved
        else ChannelApprovalStatus.REJECTED,
    )
    channel.reviewed_by = ctx.user.id
    channel.reviewed_at = now
    channel.decision_comment = comment

    latest = _latest_approval(db, channel.id)
    if latest is not None:
        latest.reviewed_by = ctx.user.id
        latest.reviewed_at = now
        latest.decision = payload.decision
        latest.comment = comment

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="channel.approve" if approved else "channel.reject",
        target_type="channel",
        target_id=channel.id,
        payload={
            "decision": payload.decision.value,
            "comment": comment,
            "code": channel.code,
        },
    )
    db.commit()
    return ok(_channel_edit_data(db, channel))


@router.get("/{channel_id}/approvals", response_model=Envelope[ChannelApprovalListData])
def list_channel_approvals(
    channel_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("channel.read")),
    db: Session = Depends(get_db),
) -> dict:
    """渠道准入审批轨迹：按提交时间正序返回全部周期。"""
    require_scoped_row(
        db,
        Channel,
        ctx.project.id,
        resource="channel",
        id=channel_id,
    )
    return ok({"approvals": _approval_history(db, channel_id)})


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
    """按项目业务时区把日期筛选取成 UTC 左闭右开边界。"""
    if start_date is not None and end_date is not None and start_date > end_date:
        raise AppError("start_date 不能晚于 end_date", code="invalid_date_range")

    try:
        tz = project_timezone(ctx.project)
    except ProjectTimezoneInvalid as exc:
        raise BusinessValidationError(
            "项目时区配置无效，无法按日期筛选导出", code="project_timezone_invalid"
        ) from exc

    start_at = local_day_start_utc(tz, start_date) if start_date is not None else None
    # 结束日期含端改为“次日零点”右开，避免把下一周期首条记录重复算入。
    end_at = (
        local_day_start_utc(tz, end_date + timedelta(days=1)) if end_date is not None else None
    )
    return start_at, end_at


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
    review_status: CitationReviewStatus | None = Query(
        None,
        description=(
            "引用复核状态；筛选导出默认只统计 manual_confirmed，"
            "传 auto 可导出未复核引用，传 manual_rejected 可导出已驳回引用"
        ),
    ),
) -> Response:
    """同步 CSV 导出：超过 export_sync_row_limit 由 record_export 抛错，要求改异步。

    无筛选参数时导出全量渠道台账；带任一筛选参数时输出按引用聚合的渠道覆盖列表。
    聚合列表默认只统计人工确认引用，避免未复核引用把渠道效果算大。
    """
    effective_review_status = review_status or CitationReviewStatus.MANUAL_CONFIRMED
    has_filter = any(
        value is not None
        for value in (engine_id, question_id, start_date, end_date, review_status)
    )
    filters: dict[str, object] = {"resource": "channels"}

    if has_filter:
        start_at, end_at = _date_window(ctx, start_date, end_date)
        statement = _filtered_channel_statement(
            ctx.project.id,
            engine_id=engine_id,
            question_id=question_id,
            start_at=start_at,
            end_at=end_at,
            review_status=effective_review_status,
        )
        # 导出的行是渠道，但真实扫描量是引用行：先按引用行数卡同步上限，
        # 否则大项目会在 record_export 之前就把整张引用表读进内存。
        citation_row_count = _count_rows(db, statement)
        ensure_sync_export_allowed(citation_row_count, what="筛选导出需扫描的引用")
        rows = _filtered_channel_rows(db, statement)
        content = _filtered_channel_csv(rows)
        if engine_id is not None:
            filters["engine_id"] = str(engine_id)
        if question_id is not None:
            filters["question_id"] = str(question_id)
        if start_date is not None:
            filters["start_date"] = start_date.isoformat()
        if end_date is not None:
            filters["end_date"] = end_date.isoformat()
        filters["review_status"] = effective_review_status.value
    else:
        rows = _all_channels(db, ctx.project.id)
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


@router.get("/anomalies", response_model=Envelope[ChannelAnomalyListData])
def get_channel_anomalies(
    ctx: ProjectContext = Depends(require_permission("channel.read")),
    db: Session = Depends(get_db),
) -> dict:
    """渠道台账与发布回执的一致性异常清单，供台账顶部提示和逐条处理。"""
    return ok(detect_channel_anomalies(db, ctx.project.id))


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
    channel = _channel_detail_row(db, ctx.project.id, channel_id)

    base = _channel_citation_statement(channel.id, ctx.project.id)
    cited = digest(db, base, page=page, page_size=page_size)

    # 域名观测：只给信源层补明细，不写 channel_id、不进 channel_count。
    domains = _channel_domains(db, channel)
    observed = _channel_observed_statement(ctx.project.id, domains)
    observed_digest = digest(db, observed, page=1, page_size=20) if observed is not None else None

    return ok(
        {
            **_channel_edit_data(db, channel),
            "citation_count": cited.citation_count,
            "sample_count": cited.sample_count,
            "page_count": cited.page_count,
            "citation_page": page,
            "citation_page_size": page_size,
            "page_urls": cited.page_urls,
            "engine_codes": cited.engine_codes,
            "question_codes": cited.question_codes,
            "first_sampled_at": cited.first_sampled_at,
            "last_sampled_at": cited.last_sampled_at,
            "citations": cited.citations,
            "approvals": _approval_history(db, channel.id),
            "observed_domain_count": len(domains),
            "observed_citation_count": observed_digest.citation_count if observed_digest else 0,
            "observed_sample_count": observed_digest.sample_count if observed_digest else 0,
            "observed_page_count": observed_digest.page_count if observed_digest else 0,
            "observed_page_urls": observed_digest.page_urls if observed_digest else [],
            "observed_engine_codes": observed_digest.engine_codes if observed_digest else [],
            "observed_question_codes": observed_digest.question_codes if observed_digest else [],
            "observed_citations": observed_digest.citations if observed_digest else [],
        }
    )

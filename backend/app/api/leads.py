"""线索接口：只有 lead.read / lead.write 能力能进来。

线索/客服（lead_ops）只持有这两项能力，因此监测、证据、内容、发布、渠道接口对他们一律 403。
"""

import csv
import io
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    LeadCreated,
    LeadData,
    LeadFunnelData,
    LeadMessageData,
    LeadVisitorReportData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.config import settings
from app.core.errors import AppError, ResourceMissingError
from app.db.session import get_db
from app.models import AiEngine, Channel, Lead, LeadMessage, Question, User
from app.models.enums import EnrollmentStatus, RoleCode
from app.schemas import LeadCreate, LeadMessageCreate, LeadUpdate
from app.services.state_machine import ensure_enrollment_transition
from app.services.audit import record_audit, record_export
from app.services.csv_safety import safe_csv_cell
from app.services.lead_listing import lead_total, owner_names, page_leads, rows_for_export
from app.services.export_guard import ensure_sync_export_allowed
from app.services.project_scope import require_scoped_row
from app.services.lead_visitors import hash_visitor, mask_hash, visitor_report
from app.services.reports import lead_funnel, resolve_date_window

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/leads",
    tags=["线索"],
    responses=COMMON_ERRORS,
)

LEAD_EXPORT_COLUMNS = (
    "id",
    "created_at",
    "contact_name",
    "contact_phone",
    "contact_wechat",
    "interested_course",
    "reported_ai_product",
    "is_valid",
    "enrollment_status",
    "lead_source",
    "source_question_id",
    "source_channel_id",
    "source_engine_id",
    "landing_url",
    "session_id",
    "utm_campaign",
    "note",
    "owner_name",
)


def _require_project_ref(db: Session, model, value, project_id, label: str) -> None:
    """归因外键必须指向当前项目的题目/渠道，避免跨项目串数。"""
    if value is None:
        return
    row = db.scalar(
        select(model.id).where(model.id == value, model.project_id == project_id)
    )
    if row is None:
        raise ResourceMissingError(f"{label}不存在或不属于当前项目")


def _require_engine(db: Session, value) -> None:
    if value is None:
        return
    if db.scalar(select(AiEngine.id).where(AiEngine.id == value)) is None:
        raise ResourceMissingError("引擎不存在")


def _mask_contact(value: str | None, prefix: int, suffix: int) -> str | None:
    if not value:
        return value
    if len(value) <= prefix + suffix:
        return "*" * len(value)
    return f"{value[:prefix]}****{value[-suffix:]}"


def _mask_phone(value: str | None) -> str | None:
    return _mask_contact(value, prefix=3, suffix=4)


def _mask_wechat(value: str | None) -> str | None:
    return _mask_contact(value, prefix=2, suffix=2)


def _should_mask_contact(ctx: ProjectContext) -> bool:
    """线索/客服和项目管理员看完整联系方式；只读账号只看脱敏值。"""
    return "lead.write" not in ctx.permissions and ctx.role != RoleCode.PROJECT_ADMIN


def _serialize(row: Lead, owner_name: str | None = None, *, mask_contact: bool = False) -> dict:
    return {
        "id": str(row.id),
        "serial_no": row.serial_no,
        "contact_name": row.contact_name,
        "contact_phone": _mask_phone(row.contact_phone) if mask_contact else row.contact_phone,
        "contact_wechat": _mask_wechat(row.contact_wechat) if mask_contact else row.contact_wechat,
        "interested_course": row.interested_course,
        "reported_ai_product": row.reported_ai_product,
        "is_valid": row.is_valid,
        "enrollment_status": row.enrollment_status,
        "lead_source": row.lead_source,
        "source_question_id": str(row.source_question_id) if row.source_question_id else None,
        "source_channel_id": str(row.source_channel_id) if row.source_channel_id else None,
        "source_engine_id": str(row.source_engine_id) if row.source_engine_id else None,
        "landing_url": row.landing_url,
        "session_id": row.session_id,
        "utm_campaign": row.utm_campaign,
        "note": row.note,
        "visitor_region": row.visitor_region,
        "visitor_hash": mask_hash(row.ip_hash),
        "owner_id": str(row.owner_id) if row.owner_id else None,
        "owner_name": owner_name,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("", response_model=PagedEnvelope[LeadData])
def list_leads(
    ctx: ProjectContext = Depends(require_permission("lead.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    total, rows = page_leads(
        db, ctx.project.id, page=page, page_size=page_size
    )
    owners = owner_names(db, rows)
    mask_contact = _should_mask_contact(ctx)
    return ok_page(
        [
            _serialize(row, owners.get(row.owner_id), mask_contact=mask_contact)
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[LeadCreated])
def create_lead(
    payload: LeadCreate,
    ctx: ProjectContext = Depends(require_permission("lead.write")),
    db: Session = Depends(get_db),
) -> dict:
    _require_project_ref(db, Question, payload.source_question_id, ctx.project.id, "题目")
    _require_project_ref(db, Channel, payload.source_channel_id, ctx.project.id, "渠道")
    _require_engine(db, payload.source_engine_id)
    lead = Lead(
        project_id=ctx.project.id,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        contact_wechat=payload.contact_wechat,
        interested_course=payload.interested_course,
        reported_ai_product=payload.reported_ai_product,
        is_valid=payload.is_valid,
        lead_source=payload.lead_source,
        source_question_id=payload.source_question_id,
        source_channel_id=payload.source_channel_id,
        source_engine_id=payload.source_engine_id,
        landing_url=payload.landing_url,
        session_id=payload.session_id,
        utm_campaign=payload.utm_campaign,
        note=payload.note,
        ip_hash=hash_visitor(payload.visitor_ip),
        visitor_region=(payload.visitor_region or "").strip() or None,
        enrollment_status=EnrollmentStatus.UNKNOWN,
        owner_id=ctx.user.id,
    )
    db.add(lead)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="lead.create",
        target_type="lead",
        target_id=lead.id,
        payload={
            "lead_source": payload.lead_source,
            "reported_ai_product": payload.reported_ai_product,
            "is_valid": payload.is_valid,
            "source_question_id": str(payload.source_question_id) if payload.source_question_id else None,
            "source_channel_id": str(payload.source_channel_id) if payload.source_channel_id else None,
            "source_engine_id": str(payload.source_engine_id) if payload.source_engine_id else None,
            "utm_campaign": payload.utm_campaign,
        },
    )
    db.commit()
    return ok({"id": str(lead.id), "serial_no": lead.serial_no})


@router.get(
    "/export",
    responses={
        200: {
            "description": "线索明细 CSV（写审计；超行数上限返回 400）",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    },
)
def export_leads_csv(
    ctx: ProjectContext = Depends(require_permission("export.data")),
    db: Session = Depends(get_db),
) -> Response:
    lead_count = lead_total(db, ctx.project.id)
    ensure_sync_export_allowed(lead_count, what="线索导出")
    rows = rows_for_export(db, ctx.project.id, settings.export_sync_row_limit)
    owners = owner_names(db, rows)
    mask_contact = _should_mask_contact(ctx)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=LEAD_EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        status = row.enrollment_status.value if hasattr(row.enrollment_status, "value") else row.enrollment_status
        writer.writerow(
            {
                "id": str(row.id),
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "contact_name": safe_csv_cell(row.contact_name or ""),
                "contact_phone": safe_csv_cell(
                    _mask_phone(row.contact_phone) if mask_contact else (row.contact_phone or "")
                ),
                "contact_wechat": safe_csv_cell(
                    _mask_wechat(row.contact_wechat) if mask_contact else (row.contact_wechat or "")
                ),
                "interested_course": safe_csv_cell(row.interested_course or ""),
                "reported_ai_product": safe_csv_cell(row.reported_ai_product or ""),
                "is_valid": "true" if row.is_valid else "false",
                "enrollment_status": status,
                "lead_source": safe_csv_cell(row.lead_source or ""),
                "source_question_id": str(row.source_question_id) if row.source_question_id else "",
                "source_channel_id": str(row.source_channel_id) if row.source_channel_id else "",
                "source_engine_id": str(row.source_engine_id) if row.source_engine_id else "",
                "landing_url": safe_csv_cell(row.landing_url or ""),
                "utm_campaign": safe_csv_cell(row.utm_campaign or ""),
                "note": safe_csv_cell(row.note or ""),
                "owner_name": safe_csv_cell(owners.get(row.owner_id, "")),
            }
        )
    record_export(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        export_type="leads",
        row_count=lead_count,
        filters={},
        mode="sync",
    )
    db.commit()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="leads-{ctx.project.code}-{stamp}.csv"'},
    )


@router.get("/funnel", response_model=Envelope[LeadFunnelData])
def get_lead_funnel(
    ctx: ProjectContext = Depends(require_permission("lead.read")),
    db: Session = Depends(get_db),
    start_date: date | None = Query(None, description="创建日期起（含），按项目时区解析"),
    end_date: date | None = Query(None, description="创建日期止（含），按项目时区解析"),
) -> dict:
    """线索漏斗：咨询 → 有效 → 已联系 → 已报名，并保留来源/渠道/题目归因。"""
    if start_date is not None and end_date is not None and start_date > end_date:
        raise AppError("start_date 不能晚于 end_date", code="invalid_date_range")
    start_at, end_at = resolve_date_window(ctx.project, start_date, end_date)
    return ok(lead_funnel(db, ctx.project.id, start_at=start_at, end_at=end_at))


@router.patch("/{lead_id}", response_model=Envelope[LeadData])
def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    ctx: ProjectContext = Depends(require_permission("lead.write")),
    db: Session = Depends(get_db),
) -> dict:
    lead = require_scoped_row(db, Lead, ctx.project.id, resource="lead", id=lead_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ResourceMissingError("没有需要更新的字段", code="empty_update")
    if changes.get("owner_id") is not None:
        owner = db.scalar(select(User).where(User.id == changes["owner_id"], User.is_active.is_(True)))
        if owner is None:
            raise ResourceMissingError("负责人不存在或已停用", code="lead_owner_missing")
    if "enrollment_status" in changes:
        changes["enrollment_status"] = ensure_enrollment_transition(
            lead.enrollment_status, changes["enrollment_status"]
        )
    for field, value in changes.items():
        setattr(lead, field, value)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="lead.update",
        target_type="lead",
        target_id=lead.id,
        payload={"fields": sorted(changes)},
    )
    db.commit()
    owner_name = db.scalar(
        select(User.display_name).where(User.id == lead.owner_id)
    ) if lead.owner_id else None
    return ok(_serialize(lead, owner_name, mask_contact=_should_mask_contact(ctx)))


@router.get("/visitor-report", response_model=Envelope[LeadVisitorReportData])
def get_visitor_report(
    ctx: ProjectContext = Depends(require_permission("lead.read")),
    db: Session = Depends(get_db),
) -> dict:
    """获客结构：去重访客 / 地区 / 渠道 / 未读留言。

    去重访客只统计带 ip_hash 的线索；手工录入（无访客地址）不参与去重，
    否则「同一个人手工录 3 次」会被算成 0 个访客，报表口径就失真。
    """
    report = visitor_report(db, ctx.project.id)
    report["by_region"] = [
        {"label": item["region"], "count": item["count"]} for item in report["by_region"]
    ]
    report["by_source"] = [
        {"label": item["source"], "count": item["count"]} for item in report["by_source"]
    ]
    return ok(report)


def _serialize_message(row: LeadMessage) -> dict:
    return {
        "id": str(row.id),
        "lead_id": str(row.lead_id),
        "author_role": row.author_role,
        "body": row.body,
        "is_read": row.is_read,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at,
    }


@router.get("/{lead_id}/messages", response_model=Envelope[list[LeadMessageData]])
def list_lead_messages(
    lead_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("lead.read")),
    db: Session = Depends(get_db),
) -> dict:
    require_scoped_row(db, Lead, ctx.project.id, resource="lead", id=lead_id)
    rows = db.execute(
        select(LeadMessage)
        .where(LeadMessage.project_id == ctx.project.id, LeadMessage.lead_id == lead_id)
        .order_by(LeadMessage.seq.asc())
    ).scalars().all()
    return ok([_serialize_message(row) for row in rows])


@router.post(
    "/{lead_id}/messages", status_code=201, response_model=Envelope[LeadMessageData]
)
def create_lead_message(
    lead_id: uuid.UUID,
    payload: LeadMessageCreate,
    ctx: ProjectContext = Depends(require_permission("lead.write")),
    db: Session = Depends(get_db),
) -> dict:
    """记一条留言。访客留言默认未读，运营回复默认已读；读状态只服务于运营侧跟进。"""
    lead = require_scoped_row(db, Lead, ctx.project.id, resource="lead", id=lead_id)
    message = LeadMessage(
        project_id=ctx.project.id,
        lead_id=lead.id,
        author_role=payload.author_role,
        body=payload.body,
        is_read=payload.author_role != "visitor",
        created_by=ctx.user.id,
    )
    db.add(message)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="lead.message",
        target_type="lead",
        target_id=lead.id,
        payload={"message_id": str(message.id), "author_role": payload.author_role},
    )
    db.commit()
    return ok(_serialize_message(message))


@router.patch(
    "/{lead_id}/messages/{message_id}", response_model=Envelope[LeadMessageData]
)
def mark_lead_message_read(
    lead_id: uuid.UUID,
    message_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("lead.write")),
    db: Session = Depends(get_db),
) -> dict:
    require_scoped_row(db, Lead, ctx.project.id, resource="lead", id=lead_id)
    message = db.scalar(
        select(LeadMessage).where(
            LeadMessage.project_id == ctx.project.id,
            LeadMessage.lead_id == lead_id,
            LeadMessage.id == message_id,
        )
    )
    if message is None:
        raise ResourceMissingError("留言不存在", code="lead_message_missing")
    message.is_read = True
    db.commit()
    return ok(_serialize_message(message))

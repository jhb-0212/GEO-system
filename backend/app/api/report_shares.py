"""月报只读分享管理：生成、列表、吊销。

对外分享属于导出行为，创建/吊销要求 `export.data`；列表只要求 `stats.read`。
令牌只在创建响应里返回一次，列表永远不回传令牌或哈希。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.db.session import get_db
from app.schemas.report_shares import ReportShareCreate
from app.services.audit import record_audit
from app.services.report_shares import (
    create_report_share,
    list_report_shares,
    revoke_report_share,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/report-shares",
    tags=["月报分享"],
    responses=COMMON_ERRORS,
)


@router.get("", response_model=Envelope[list])
def list_shares(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    snapshot_id: uuid.UUID | None = Query(None, description="只看某份月报快照"),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    return ok(
        list_report_shares(
            db,
            project_id=ctx.project.id,
            snapshot_id=snapshot_id,
            limit=limit,
        )
    )


@router.post("", status_code=201, response_model=Envelope[dict])
def create_share(
    payload: ReportShareCreate,
    ctx: ProjectContext = Depends(require_permission("export.data")),
    db: Session = Depends(get_db),
) -> dict:
    row, token = create_report_share(
        db,
        project=ctx.project,
        snapshot_id=payload.snapshot_id,
        actor_id=ctx.user.id,
        label=payload.label,
        password=payload.password,
        expires_in_days=payload.expires_in_days,
        brand_name=payload.brand_name,
        brand_logo_url=payload.brand_logo_url,
        accent_color=payload.accent_color,
        contact_text=payload.contact_text,
        show_leads=payload.show_leads,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="report_share.create",
        target_type="report_share",
        target_id=row.id,
        payload={
            "snapshot_id": str(row.snapshot_id),
            "expires_at": row.expires_at.isoformat(),
            "password_enabled": row.password_hash is not None,
            "show_leads": row.show_leads,
            "brand_name": row.brand_name,
        },
    )
    db.commit()
    return ok(
        {
            "share_id": str(row.id),
            "snapshot_id": str(row.snapshot_id),
            "token": token,
            "share_path": f"/share/{token}",
            "expires_at": row.expires_at,
            "password_enabled": row.password_hash is not None,
        }
    )


@router.post("/{share_id}/revoke", response_model=Envelope[dict])
def revoke_share(
    share_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("export.data")),
    db: Session = Depends(get_db),
) -> dict:
    result = revoke_report_share(
        db,
        project_id=ctx.project.id,
        share_id=share_id,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="report_share.revoke",
        target_type="report_share",
        target_id=share_id,
        payload={"snapshot_id": result["snapshot_id"]},
    )
    db.commit()
    return ok(result)

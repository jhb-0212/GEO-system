"""渠道台账与导出：导出必须走 export.data 能力，并且一定写审计。"""

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, ChannelData, PagedEnvelope, ok_page
from app.db.session import get_db
from app.models import Channel
from app.services.audit import record_export

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/channels",
    tags=["渠道"],
    responses=COMMON_ERRORS,
)

CSV_COLUMNS = ("code", "name", "category", "status", "primary_domain")


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
) -> Response:
    """同步 CSV 导出：超过 export_sync_row_limit 由 record_export 抛错，要求改异步。"""
    rows = db.scalars(
        select(Channel).where(Channel.project_id == ctx.project.id).order_by(Channel.code)
    ).all()

    record_export(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        export_type="channels",
        row_count=len(rows),
        filters={"resource": "channels"},
        mode="sync",
    )
    db.commit()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"channels-{ctx.project.code}-{stamp}.csv"
    return Response(
        content=_channel_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

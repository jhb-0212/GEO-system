"""渠道台账与导出：导出必须走 export.data 能力，并且一定写审计。"""

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import ok
from app.db.session import get_db
from app.models import Channel
from app.services.audit import record_export

router = APIRouter(prefix="/api/v1/projects/{project_id}/channels", tags=["渠道"])

CSV_COLUMNS = ("code", "name", "category", "status", "primary_domain")


@router.get("")
def list_channels(
    ctx: ProjectContext = Depends(require_permission("channel.read")),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(
        select(Channel).where(Channel.project_id == ctx.project.id).order_by(Channel.code)
    ).all()
    return ok(
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
        ]
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


@router.get("/export")
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

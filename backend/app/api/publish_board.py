"""发布回链看板 + CSV 导出。

看板只读聚合；导出与看板同一口径（同一个 service 调用），避免两处数字漂移。
"""

import csv
import io
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, PublishBoardData, ok
from app.db.session import get_db
from app.services.audit import record_export
from app.services.csv_safety import safe_csv_cell
from app.services.export_guard import ensure_sync_export_allowed
from app.services.publish_board import batches, board

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/publish-board",
    tags=["发布回链"],
    responses=COMMON_ERRORS,
)

EXPORT_COLUMNS = [
    "task_serial_no",
    "channel_name",
    "content_title",
    "published_url",
    "published_host",
    "received_at",
    "visibility_matched",
    "visibility_position",
    "visibility_error_code",
    "cited",
]


@router.get("", response_model=Envelope[PublishBoardData])
def get_board(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
) -> dict:
    return ok(board(db, ctx.project.id))


@router.get("/batches", response_model=Envelope[dict])
def get_batches(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """按投喂批次聚合：这一批的任务发到哪一段、卡在哪一段。"""
    return ok(batches(db, ctx.project.id, limit=limit))


@router.get(
    "/export",
    responses={
        200: {
            "description": "发布回链 CSV（写审计；行数超过同步导出上限时返回 400）",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    },
)
def export_board(
    ctx: ProjectContext = Depends(require_permission("export.data")),
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=1000),
) -> Response:
    payload = board(db, ctx.project.id, limit=limit)
    rows = payload["items"]
    ensure_sync_export_allowed(len(rows), what="发布回链导出")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: safe_csv_cell(row.get(key)) for key in EXPORT_COLUMNS})

    record_export(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        export_type="publish_board",
        row_count=len(rows),
        filters={},    )
    db.commit()

    filename = f"publish-board-{uuid.uuid4().hex[:8]}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

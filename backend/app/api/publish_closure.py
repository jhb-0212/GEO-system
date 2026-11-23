"""发布闭环看板：以任务为轴看断在哪一环。只读聚合，不改发布状态。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.db.session import get_db
from app.services.publish_closure import closure

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/publish-closure",
    tags=["发布闭环"],
    responses=COMMON_ERRORS,
)


@router.get("", response_model=Envelope[dict])
def publish_closure(
    ctx: ProjectContext = Depends(require_permission("publish.read")),
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=500),
):
    return ok(closure(db, ctx.project.id, limit=limit))

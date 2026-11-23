"""B3 流量接口：三个计数并列，分布只给事件数与去重访客。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.db.session import get_db
from app.services.traffic import summary

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/traffic",
    tags=["流量"],
    responses=COMMON_ERRORS,
)


@router.get("/summary", response_model=Envelope[dict])
def get_summary(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
) -> dict:
    return ok(summary(db, ctx.project.id, days=days))

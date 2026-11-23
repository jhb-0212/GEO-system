"""B1 双轨大屏接口：两列事实，不合成总分。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.db.session import get_db
from app.services.dashboard_tracks import tracks_snapshot

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/dashboard",
    tags=["大屏"],
    responses=COMMON_ERRORS,
)


@router.get("/tracks", response_model=Envelope[dict])
def get_tracks(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365, description="近 N 天窗口，只用在一侧的时间维度"),
) -> dict:
    return ok(tracks_snapshot(db, ctx.project.id, days=days))

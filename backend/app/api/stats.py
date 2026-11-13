"""统计接口：GEO 内部验收指标只读端点。

与 `services/stats.py::geo_overview` 共用同一套口径，HTTP 层不重新解释指标；
项目隔离由 `require_permission("stats.read")` + 服务层 `project_id` 过滤共同保证。
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, GeoOverviewData, ok
from app.db.session import get_db
from app.services.stats import geo_overview

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/stats",
    tags=["统计"],
    responses=COMMON_ERRORS,
)


@router.get("/geo", response_model=Envelope[GeoOverviewData])
def get_geo_overview(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    round_id: uuid.UUID | None = Query(None, description="按监测轮次过滤"),
    engine_id: uuid.UUID | None = Query(None, description="按引擎过滤"),
    question_id: uuid.UUID | None = Query(None, description="按题目过滤"),
    start_at: datetime | None = Query(None, description="样本采样时间下限，ISO 8601"),
    end_at: datetime | None = Query(None, description="样本采样时间上限，ISO 8601"),
) -> dict:
    return ok(
        geo_overview(
            db,
            ctx.project.id,
            round_id=round_id,
            engine_id=engine_id,
            question_id=question_id,
            start_at=start_at,
            end_at=end_at,
        )
    )

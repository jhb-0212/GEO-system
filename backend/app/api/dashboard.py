"""B1 双轨大屏接口：两列事实，不合成总分。

`/board` 是同一路由下的演示屏：单一视图、四个主数、口径写在返回体里；
两项共用 `stats.read`，不额外放宽权限。
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.db.session import get_db
from app.services.dashboard_board import board_snapshot
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


@router.get("/board", response_model=Envelope[dict])
def get_board(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365, description="近 N 天窗口；KPI 增量、趋势与平台占比都按这个窗口"),
    engine_id: uuid.UUID | None = Query(None, description="报表明细按引擎筛选；不传为全部"),
    page: int = Query(1, ge=1, description="报表明细分页，从 1 开始"),
    page_size: int = Query(10, ge=1, le=50),
    report_kind: Literal["all", "search", "qa", "intent", "brand"] = Query(
        "all", description="报表类型：全部 / 搜索（检索结果类样本）/ 问答（生成回答类样本）/ 意图（问题带意图）/ 品牌（命中品牌）"
    ),
    device: Literal["all", "pc", "mobile"] = Query(
        "all", description="采集端：all 全部（含官方 API）/ pc 网页用户端 / mobile 客户端与应用内搜索"
    ),
    lead_page: int = Query(1, ge=1, description="线索事件分页，从 1 开始"),
    lead_page_size: int = Query(10, ge=1, le=50),
) -> dict:
    return ok(
        board_snapshot(
            db,
            ctx.project.id,
            days=days,
            engine_id=engine_id,
            page=page,
            page_size=page_size,
            report_kind=report_kind,
            device=device,
            lead_page=lead_page,
            lead_page_size=lead_page_size,
        )
    )

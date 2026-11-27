"""B1 双轨大屏接口：两列事实，不合成总分。

`/board` 是同一路由下的演示屏：单一视图、四个主数、口径写在返回体里；
两项共用 `stats.read`，不额外放宽权限。
"""

import uuid
from datetime import date
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.db.session import get_db
from app.services.dashboard_board import board_snapshot, report_csv
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
    device: Literal["all", "pc", "mobile", "api"] = Query(
        "all", description="采集端：all 全部合并 / pc 网页用户端 / mobile 客户端与应用内搜索 / api 官方 API"
    ),
    lead_page: int = Query(1, ge=1, description="线索事件分页，从 1 开始"),
    lead_page_size: int = Query(10, ge=1, le=50),
    lead_kind: Literal["all", "traffic", "lead"] = Query(
        "all", description="线索事件类型：all 全部 / traffic 访问事件 / lead 表单线索"
    ),
    lead_region: str | None = Query(None, max_length=64, description="线索事件地区：按 visitor_region 精确匹配，不传为全部"),
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
            lead_kind=lead_kind,
            lead_region=lead_region,
        )
    )


@router.get(
    "/board/report.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "报表明细 CSV，UTF-8 BOM，Excel 可直接打开"}},
)
def get_board_report_csv(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365, description="近 N 天窗口，与 /board 同一口径"),
    engine_id: uuid.UUID | None = Query(None, description="按引擎筛选；不传为全部"),
    report_kind: Literal["all", "search", "qa", "intent", "brand"] = Query("all"),
    device: Literal["all", "pc", "mobile", "api"] = Query("all", description="采集端筛选，与 /board 同一口径"),
) -> Response:
    """一次查询导出整个窗口的报表明细，不受分页限制（上限 5000 行）。"""
    content = report_csv(
        db,
        ctx.project.id,
        days=days,
        engine_id=engine_id,
        kind=report_kind,
        device=device,
    )
    filename = f"GEO报表明细-{date.today().isoformat()}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="geo-report.csv"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )

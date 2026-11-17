"""统计接口：GEO 内部验收指标只读端点。

与 `services/stats.py::geo_overview` 共用同一套口径，HTTP 层不重新解释指标；
项目隔离由 `require_permission("stats.read")` + 服务层 `project_id` 过滤共同保证。
"""

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    EngineHealthData,
    EngineTaskShare,
    Envelope,
    GeoOverviewData,
    StatsEngineData,
    StatsOverviewData,
    StatsQuestionData,
    StatsSourceData,
    StatsTrendPoint,
    ok,
)
from app.db.session import get_db
from app.models import AiEngine, AiEngineEntry, MonitoringTask
from app.services.audit import record_export
from app.services.stats import STATS_EXPORT_COLUMNS
from app.services.stats import by_engine, by_question, engine_health, geo_overview, overview, sources
from app.services.stats import export as export_stats

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/stats",
    tags=["统计"],
    responses=COMMON_ERRORS,
)


def _filters(
    round_id: uuid.UUID | None = Query(None),
    engine_id: uuid.UUID | None = Query(None),
    question_id: uuid.UUID | None = Query(None),
    start_at: datetime | None = Query(None),
    end_at: datetime | None = Query(None),
) -> dict:
    return {
        "round_id": round_id,
        "engine_id": engine_id,
        "question_id": question_id,
        "start_at": start_at,
        "end_at": end_at,
    }


@router.get("/overview", response_model=Envelope[StatsOverviewData])
def get_overview(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    filters: dict = Depends(_filters),
) -> dict:
    return ok(overview(db, ctx.project.id, **filters))


@router.get("/by-engine", response_model=Envelope[list[StatsEngineData]])
def get_by_engine(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    filters: dict = Depends(_filters),
) -> dict:
    return ok(by_engine(db, ctx.project.id, **filters))


@router.get("/sources", response_model=Envelope[list[StatsSourceData]])
def get_sources(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    filters: dict = Depends(_filters),
    limit: int = Query(20, ge=1, le=200, description="返回的域名条数上限"),
) -> dict:
    """信源分布：AI 从哪些域名取证。

    与「渠道被引」分开看：`channel_citations` 才是有发布回执支撑的渠道效果，
    其余是第三方信源，用于选题（该去哪发），不进渠道台账。
    """
    return ok(sources(db, ctx.project.id, limit=limit, **filters))


@router.get("/engine-health", response_model=Envelope[list[EngineHealthData]])
def get_engine_health(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    round_id: uuid.UUID | None = Query(None, description="按监测轮次过滤"),
    start_at: datetime | None = Query(None, description="样本采样时间下限，ISO 8601"),
    end_at: datetime | None = Query(None, description="样本采样时间上限，ISO 8601"),
) -> dict:
    """入口级真实可用性矩阵：配置状态、失败率、平均延迟、token 与估算费用。"""
    return ok(
        engine_health(
            db,
            ctx.project.id,
            round_id=round_id,
            start_at=start_at,
            end_at=end_at,
        )
    )


@router.get("/by-question", response_model=Envelope[list[StatsQuestionData]])
def get_by_question(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    filters: dict = Depends(_filters),
) -> dict:
    return ok(by_question(db, ctx.project.id, **filters))


@router.get(
    "/export",
    responses={
        200: {
            "description": "统计总览 + 分引擎 + 分问题 CSV（写审计；超行数上限返回 400）",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    },
)
def export_stats_csv(
    ctx: ProjectContext = Depends(require_permission("export.data")),
    db: Session = Depends(get_db),
    filters: dict = Depends(_filters),
) -> Response:
    """导出看板同一口径的统计行；不重新写 SQL，避免导出与看板数字漂移。"""
    rows = export_stats(db, ctx.project.id, **filters)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=STATS_EXPORT_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)

    audit_filters = {"resource": "stats"}
    for key, value in filters.items():
        if value is None:
            continue
        audit_filters[key] = value.isoformat() if isinstance(value, datetime) else str(value)

    record_export(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        export_type="stats",
        row_count=len(rows),
        filters=audit_filters,
        mode="sync",
    )
    db.commit()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"stats-{ctx.project.code}-{stamp}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/trend", response_model=Envelope[list[StatsTrendPoint]])
def get_weekly_trend(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    weeks: int = Query(12, ge=1, le=12),
) -> dict:
    """Use the existing overview calculation for each week to keep one metric definition."""
    now = datetime.now(timezone.utc)
    current_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    result = []
    for offset in range(weeks - 1, -1, -1):
        week_start = current_week - timedelta(weeks=offset)
        week_end = week_start + timedelta(weeks=1) - timedelta(microseconds=1)
        metric = overview(db, ctx.project.id, start_at=week_start, end_at=week_end)
        result.append({
            "week_start": week_start,
            "valid_answers": metric["valid_answers"],
            "brand_mention_rate": metric["brand_mention_rate"],
        })
    return ok(result)


@router.get("/task-distribution", response_model=Envelope[list[EngineTaskShare]])
def get_task_distribution(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    round_id: uuid.UUID | None = Query(None),
) -> dict:
    filters = [MonitoringTask.project_id == ctx.project.id]
    if round_id is not None:
        filters.append(MonitoringTask.round_id == round_id)
    rows = db.execute(
        select(AiEngine.id, AiEngine.name, func.count(MonitoringTask.id))
        .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
        .join(MonitoringTask, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .where(*filters)
        .group_by(AiEngine.id, AiEngine.name)
        .order_by(AiEngine.name)
    ).all()
    total = sum(count for _, _, count in rows)
    return ok([
        {
            "engine_id": str(engine_id),
            "engine_name": engine_name,
            "task_count": count,
            "share": round(count * 100 / total, 2),
        }
        for engine_id, engine_name, count in rows
    ])


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

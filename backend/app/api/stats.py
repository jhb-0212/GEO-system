"""统计接口：GEO 内部验收指标只读端点。

与 `services/stats.py::geo_overview` 共用同一套口径，HTTP 层不重新解释指标；
项目隔离由 `require_permission("stats.read")` + 服务层 `project_id` 过滤共同保证。
"""

import csv
import io
import uuid
from datetime import datetime, timezone

import httpx
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
    StatsAnswerKindOverviewData,
    StatsOverviewData,
    StatsPublishVisibilityCheckData,
    StatsPublishVisibilityData,
    StatsQuestionData,
    StatsSourceData,
    StatsTrendPoint,
    ok,
)
from app.core.credentials import read_credential_env
from app.core.errors import ConflictError, TooManyRequestsError
from app.db.session import get_db
from app.models import AiEngine, AiEngineEntry, MonitoringTask
from app.models.enums import AnswerKind
from app.services.audit import record_audit, record_export
from app.services.csv_safety import safe_csv_cell
from app.services.export_guard import ensure_sync_export_allowed
from app.services.publish_visibility import (
    DEFAULT_CREDENTIAL_REF,
    check_project,
    latest_checks,
)
from app.services.rate_limit import ProjectCooldown
from app.services.stats import STATS_EXPORT_COLUMNS
from app.services.stats import (
    by_engine,
    by_question,
    engine_health,
    geo_overview,
    overview,
    overview_by_answer_kind,
    sources,
    weekly_trend,
)
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
    answer_kind: AnswerKind | None = Query(
        None, description="答案口径：answer / search_result；不传则按全部样本（融合口径）"
    ),
) -> dict:
    return {
        "round_id": round_id,
        "engine_id": engine_id,
        "question_id": question_id,
        "start_at": start_at,
        "end_at": end_at,
        "answer_kind": answer_kind,
    }


@router.get("/overview", response_model=Envelope[StatsOverviewData])
def get_overview(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    filters: dict = Depends(_filters),
) -> dict:
    return ok(overview(db, ctx.project.id, **filters))


@router.get(
    "/overview-by-answer-kind",
    response_model=Envelope[list[StatsAnswerKindOverviewData]],
)
def get_overview_by_answer_kind(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    filters: dict = Depends(_filters),
) -> dict:
    """答案口径分组：answer / search_result 分开返回，不提供合并后的总提及率。"""
    filters.pop("answer_kind", None)
    return ok(overview_by_answer_kind(db, ctx.project.id, **filters))


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


@router.get("/publish-visibility", response_model=Envelope[list[StatsPublishVisibilityData]])
def get_publish_visibility(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200, description="返回的回执条数上限"),
) -> dict:
    """发布可见性：发出去的回执页面能不能被搜索引擎检索到。

    只做诊断，不参与渠道归因；`error_code` 非空表示没查成，不等于"没被收录"。
    """
    return ok(latest_checks(db, ctx.project.id, limit=limit))


# 同项目 60 秒内只允许触发一次：一次批量检测就是一批外部付费调用，防连点烧配额。
_VISIBILITY_THROTTLE_SECONDS = 60.0
_visibility_cooldown = ProjectCooldown(
    namespace="stats:publish_visibility",
    seconds=_VISIBILITY_THROTTLE_SECONDS,
)


@router.post(
    "/publish-visibility/check",
    response_model=Envelope[StatsPublishVisibilityCheckData],
)
def trigger_publish_visibility_check(
    ctx: ProjectContext = Depends(require_permission("monitoring.execute")),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=50, description="本次最多检测几条回执，按回执时间倒序"),
) -> dict:
    """手动触发一次发布可见性检测。

    需要 `monitoring.execute`（会真实调用外部搜索接口并写库）；同一项目 60 秒节流，
    避免连点重复烧掉免费额度。返回本次汇总，明细仍在 `GET /publish-visibility`。
    """
    api_key = read_credential_env(DEFAULT_CREDENTIAL_REF)
    if not api_key:
        raise ConflictError(
            f"环境变量 {DEFAULT_CREDENTIAL_REF} 未配置，无法调用搜索接口",
            code="credential_missing",
        )

    wait = _visibility_cooldown.acquire(ctx.project.id)
    if wait > 0:
        raise TooManyRequestsError(f"检测过于频繁，请 {wait} 秒后再试")

    try:
        with httpx.Client(timeout=30.0) as client:
            summary = check_project(db, ctx.project.id, client=client, api_key=api_key, limit=limit)
        record_audit(
            db,
            project_id=ctx.project.id,
            actor_id=ctx.user.id,
            action="stats.publish_visibility.check",
            target_type="project",
            target_id=ctx.project.id,
            payload={"limit": limit, **summary},
        )
        db.commit()
    except Exception:
        # 检测/落库失败不能把用户锁在 60 秒窗口里；释放后允许立刻重试。
        _visibility_cooldown.release(ctx.project.id)
        raise
    return ok(summary)


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
            "description": "统计总览 + 分引擎 + 分问题 CSV（聚合导出，写审计；行数超过 export_sync_row_limit 时由同步导出守卫返回 400）",
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
    # 统计导出是聚合行（引擎数 + 题目数），实际不会接近上限；接入同一守卫是为了
    # 让「同步导出必须过上限检查」这条规则在所有导出接口上成立，不靠约定。
    # 这里与 channels / leads 不同，必须「先聚合再判」：统计导出的行数由聚合维度与筛选
    # 共同决定，聚合前无法得到行数，提前判断等于再算一遍聚合。聚合行数的上界是各维度
    # 的乘积（天 × 引擎 × 问题 × 筛选），随项目规模增长而不是随明细行数增长；若将来维度
    # 乘积可能逼近 export_sync_row_limit，应在 export_stats 内部按维度提前估算，
    # 而不是退回到「先判后算」。"聚合结果量级很小"是推断而非实测，别把它当容量结论。
    ensure_sync_export_allowed(len(rows), what="统计导出")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=STATS_EXPORT_COLUMNS)
    writer.writeheader()
    writer.writerows(
        [{key: safe_csv_cell(value) for key, value in row.items()} for row in rows]
    )

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
    """按周聚合一次取数；口径仍由 services.stats 统一决定。"""
    return ok(weekly_trend(db, ctx.project.id, weeks=weeks))


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

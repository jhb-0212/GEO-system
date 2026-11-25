"""G1/G2 生成批次：建批（只有缺口来源）、跑批（模板合成）、审稿、导出。"""

import csv
import io
import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.core.errors import AppError
from app.db.session import get_db
from app.services.queries import fetch_one
from app.models import GenerationBatch
from app.schemas.generation import (
    GenerationBatchCreate,
    GenerationGateApprovalRequest,
    GenerationItemReview,
    GenerationSampleReviewRequest,
)
from app.services.audit import record_audit, record_export
from app.services.csv_safety import safe_csv_cell
from app.services.export_guard import ensure_sync_export_allowed
from app.services import generation_gate
from app.services.generation import (
    batch_snapshot,
    create_batch,
    export_rows,
    list_batches,
    review_item,
    run_batch,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/generation-batches",
    tags=["生成批次"],
    responses=COMMON_ERRORS,
)

EXPORT_COLUMNS = ["批次", "标题", "状态", "来源", "缺口类型", "问题", "已审", "正文"]


def _batch(db: Session, project_id: uuid.UUID, batch_id: uuid.UUID) -> GenerationBatch:
    batch = fetch_one(
        db, GenerationBatch, project_id=project_id, id=batch_id
    )
    if batch is None:
        raise AppError("批次不存在或不属于当前项目", code="generation_batch_not_found")
    return batch


@router.get("", response_model=Envelope[list])
def list_all(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    return ok(list_batches(db, ctx.project.id, limit=limit))


@router.post("", response_model=Envelope[dict])
def create(
    payload: GenerationBatchCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    snapshot = create_batch(
        db,
        ctx.project.id,
        name=payload.name,
        source=payload.source,
        limit=payload.limit,
        engine_code=payload.engine_code,
        note=payload.note,
        created_by=ctx.user.id,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="generation.batch.create",
        target_type="generation_batch",
        target_id=snapshot["batch_id"],
        payload={"source": payload.source, "total": snapshot["totals"]["total"]},
    )
    db.commit()
    return ok(snapshot)


@router.get("/{batch_id}", response_model=Envelope[dict])
def detail(
    batch_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    return ok(batch_snapshot(db, _batch(db, ctx.project.id, batch_id)))


@router.post("/{batch_id}/run", response_model=Envelope[dict])
def run(
    batch_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    snapshot = run_batch(db, ctx.project.id, batch_id)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="generation.batch.run",
        target_type="generation_batch",
        target_id=batch_id,
        payload={"drafted": snapshot["totals"]["drafted"], "failed": snapshot["totals"]["failed"]},
    )
    db.commit()
    return ok(snapshot)


@router.patch("/{batch_id}/items/{item_id}", response_model=Envelope[dict])
def review(
    batch_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: GenerationItemReview,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    item = review_item(db, ctx.project.id, batch_id, item_id, reviewed=payload.reviewed)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="generation.item.review",
        target_type="generation_item",
        target_id=item_id,
        payload={"reviewed": payload.reviewed},
    )
    db.commit()
    return ok({"item_id": item.id, "reviewed": item.reviewed})


@router.get(
    "/{batch_id}/export",
    response_class=Response,
    responses={
        200: {
            "description": "生成批次 CSV（写审计；超过同步导出上限返回 400）",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    },
)
def export(
    batch_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("export.data")),
    db: Session = Depends(get_db),
):
    batch = _batch(db, ctx.project.id, batch_id)
    rows = export_rows(db, batch)
    ensure_sync_export_allowed(len(rows), what="生成批次导出")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: safe_csv_cell(row.get(key)) for key in EXPORT_COLUMNS})

    record_export(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        export_type="generation_batch",
        row_count=len(rows),
        filters={"batch_id": str(batch_id)},
    )
    db.commit()

    filename = f"generation-{batch.id.hex[:8]}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---- 批次闸门（G9 第二道）：precheck → sample-review → approval → 全量 run ----
# 规模低于 GATE_MIN_ITEMS 的批次不需要过闸门，run 照旧直接跑。


@router.post("/{batch_id}/precheck", response_model=Envelope[dict])
def precheck(
    batch_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    """批次结构体检：来源能否回溯、有无事实与品牌、引擎是否可用。只诊断，不改生成项。"""
    batch = _batch(db, ctx.project.id, batch_id)
    row = generation_gate.precheck(db, project_id=ctx.project.id, batch=batch, actor_id=ctx.user.id)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="generation.gate.precheck",
        target_type="generation_gate_result",
        target_id=row.id,
        payload={"passed": row.passed, "blockers": len(row.blockers)},
    )
    db.commit()
    return ok(generation_gate.gate_payload(row))


@router.post("/{batch_id}/sample-review", response_model=Envelope[dict])
def sample_review(
    batch_id: uuid.UUID,
    payload: GenerationSampleReviewRequest,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    """先出 N 篇小样并按六项分项打分；样本项会真的生成正文并转为 drafted。"""
    batch = _batch(db, ctx.project.id, batch_id)
    row = generation_gate.sample_review(
        db,
        project_id=ctx.project.id,
        batch=batch,
        actor_id=ctx.user.id,
        sample_size=payload.sample_size,
        threshold=payload.threshold,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="generation.gate.sample_review",
        target_type="generation_gate_result",
        target_id=row.id,
        payload={"passed": row.passed, "score": row.score, "threshold": row.threshold},
    )
    db.commit()
    return ok(generation_gate.gate_payload(row))


@router.post("/{batch_id}/gate-approval", response_model=Envelope[dict])
def gate_approval(
    batch_id: uuid.UUID,
    payload: GenerationGateApprovalRequest,
    ctx: ProjectContext = Depends(require_permission("content.review")),
    db: Session = Depends(get_db),
) -> dict:
    """审核人签核放行；小样未通过时拒绝（签核不能替代打分）。"""
    batch = _batch(db, ctx.project.id, batch_id)
    row = generation_gate.approve(
        db,
        project_id=ctx.project.id,
        batch=batch,
        actor_id=ctx.user.id,
        note=payload.note,
    )
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="generation.gate.approval",
        target_type="generation_gate_result",
        target_id=row.id,
        payload={"note": payload.note},
    )
    db.commit()
    return ok(generation_gate.gate_payload(row))


@router.get("/{batch_id}/gates", response_model=Envelope[list])
def list_gates(
    batch_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    batch = _batch(db, ctx.project.id, batch_id)
    return ok([generation_gate.gate_payload(row) for row in generation_gate.page_gates(db, batch)])

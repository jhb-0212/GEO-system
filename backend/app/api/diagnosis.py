"""诊断报告：B6 报告 + B4 五维分项数字，只读。

分项口径见 `docs/metric-dictionary.md`；HTTP 层不做任何重算，
`value` 为 `null` 表示该分项在当前筛选范围内没有分母。
"""

import csv
import io
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, DiagnosisReportData, Envelope, ok
from app.api.stats import _filters
from app.db.session import get_db
from app.services.audit import record_export
from app.services.csv_safety import safe_csv_cell
from app.services.diagnosis_report import diagnosis_report
from app.services.export_guard import ensure_sync_export_allowed

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/diagnosis-report",
    tags=["诊断报告"],
    responses=COMMON_ERRORS,
)

EXPORT_COLUMNS = ["key", "label", "value_percent", "numerator", "denominator", "definition", "basis"]


@router.get("", response_model=Envelope[DiagnosisReportData])
def get_diagnosis_report(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    filters: dict = Depends(_filters),
) -> dict:
    return ok(diagnosis_report(db, ctx.project.id, **filters))


@router.get(
    "/export",
    responses={
        200: {
            "description": "诊断报告五维分项 CSV（与页面同一口径，写审计）",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    },
)
def export_diagnosis_report(
    ctx: ProjectContext = Depends(require_permission("export.data")),
    db: Session = Depends(get_db),
    filters: dict = Depends(_filters),
) -> Response:
    """导出页面上的同一份数字：不重新定义口径，也不补算缺失项。"""
    payload = diagnosis_report(db, ctx.project.id, **filters)
    rows = [
        {
            "key": row["key"],
            "label": row["label"],
            "value_percent": "" if row["value"] is None else f"{row['value'] * 100:.2f}",
            "numerator": row["numerator"],
            "denominator": row["denominator"],
            "definition": row["definition"],
            "basis": row["basis"],
        }
        for row in payload["dimensions"]
    ]
    ensure_sync_export_allowed(len(rows), what="诊断报告导出")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: safe_csv_cell(row.get(key)) for key in EXPORT_COLUMNS})

    record_export(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        export_type="diagnosis_report",
        row_count=len(rows),
        filters={key: str(value) for key, value in filters.items() if value is not None},
    )
    db.commit()

    filename = f"diagnosis-report-{uuid.uuid4().hex[:8]}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

"""诊断报告：B6 报告 + B4 五维分项数字，只读。

分项口径见 `docs/metric-dictionary.md`；HTTP 层不做任何重算，
`value` 为 `null` 表示该分项在当前筛选范围内没有分母。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, DiagnosisReportData, Envelope, ok
from app.api.stats import _filters
from app.db.session import get_db
from app.services.diagnosis_report import diagnosis_report

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/diagnosis-report",
    tags=["诊断报告"],
    responses=COMMON_ERRORS,
)


@router.get("", response_model=Envelope[DiagnosisReportData])
def get_diagnosis_report(
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
    filters: dict = Depends(_filters),
) -> dict:
    return ok(diagnosis_report(db, ctx.project.id, **filters))

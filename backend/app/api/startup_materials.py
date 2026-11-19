"""启动材料待补清单：只读盘点，缺失项显式返回。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, StartupMaterialsData, ok
from app.db.session import get_db
from app.services.startup_materials import startup_materials

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/startup-materials",
    tags=["启动材料"],
    responses=COMMON_ERRORS,
)


@router.get("/gaps", response_model=Envelope[StartupMaterialsData])
def get_startup_material_gaps(
    ctx: ProjectContext = Depends(require_permission("project.read")),
    db: Session = Depends(get_db),
) -> dict:
    """返回域名/CMS、平台账号、路线大纲、案例、招生就业口径与待补清单。"""
    return ok(startup_materials(db, ctx.project.id))

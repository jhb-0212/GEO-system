"""AI 引擎目录：系统参考数据，只有系统管理员可维护；读取对登录用户开放。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_system_permission
from app.api.responses import ok
from app.core.errors import AppError
from app.db.session import get_db
from app.models import AiEngine, User
from app.schemas import EngineCreate
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/engines", tags=["引擎目录"])


def _serialize(engine: AiEngine) -> dict:
    return {
        "id": str(engine.id),
        "code": engine.code,
        "name": engine.name,
        "vendor": engine.vendor,
        "is_active": engine.is_active,
    }


@router.get("")
def list_engines(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(select(AiEngine).order_by(AiEngine.code)).all()
    return ok([_serialize(row) for row in rows])


@router.post("", status_code=201)
def create_engine(
    payload: EngineCreate,
    user: User = Depends(require_system_permission("engine.manage")),
    db: Session = Depends(get_db),
) -> dict:
    if db.scalar(select(AiEngine).where(AiEngine.code == payload.code)) is not None:
        raise AppError("引擎 code 已存在", code="engine_code_exists")

    engine = AiEngine(
        code=payload.code,
        name=payload.name,
        vendor=payload.vendor,
        supports_search=payload.supports_search,
        supports_citation=payload.supports_citation,
        is_active=True,
    )
    db.add(engine)
    db.flush()
    record_audit(
        db,
        project_id=None,
        actor_id=user.id,
        action="engine.create",
        target_type="ai_engine",
        target_id=engine.id,
        payload={"code": engine.code},
    )
    db.commit()
    return ok(_serialize(engine))

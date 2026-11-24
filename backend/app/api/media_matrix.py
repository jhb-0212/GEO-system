"""媒体资源矩阵目录：公开只读 + 系统管理员维护。

目录是平台级配置，不按项目隔离；客户各自的渠道台账仍走 channels.py。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.core.errors import SystemAdminOnlyError
from app.db.session import get_db
from app.models import MediaMatrixConfig, User
from app.schemas.media_matrix import MediaMatrixConfigUpdate
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/media-matrix", tags=["媒体资源矩阵"], responses=COMMON_ERRORS)

CONFIG_KEY = "default"


def _require_system_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_system_admin:
        raise SystemAdminOnlyError("仅系统管理员可维护媒体资源矩阵")
    return user


def _get_config(db: Session) -> MediaMatrixConfig | None:
    return db.scalar(select(MediaMatrixConfig).where(MediaMatrixConfig.key == CONFIG_KEY))


def _config_data(row: MediaMatrixConfig | None) -> dict:
    if row is None:
        return {"payload": None, "updated_at": None, "updated_by": None, "note": None}
    return {
        "payload": row.payload,
        "updated_at": row.updated_at,
        "updated_by": str(row.updated_by) if row.updated_by else None,
        "note": row.note,
    }


@router.get("/catalog", response_model=Envelope[dict])
def get_catalog(db: Session = Depends(get_db)) -> dict:
    """公开页读取；没有保存过配置时返回 payload=null，由前端回落到默认目录。"""
    return ok(_config_data(_get_config(db)))


@router.get("/config", response_model=Envelope[dict])
def get_config(
    admin: User = Depends(_require_system_admin),
    db: Session = Depends(get_db),
) -> dict:
    return ok(_config_data(_get_config(db)))


@router.put("/config", response_model=Envelope[dict])
def save_config(
    body: MediaMatrixConfigUpdate,
    admin: User = Depends(_require_system_admin),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_config(db)
    payload = [category.model_dump(exclude_none=True) for category in body.payload]
    if row is None:
        row = MediaMatrixConfig(key=CONFIG_KEY, payload=payload)
        db.add(row)
    else:
        row.payload = payload
        row.note = body.note
    row.updated_by = admin.id
    db.flush()
    record_audit(
        db,
        project_id=None,
        actor_id=admin.id,
        action="media_matrix.update",
        target_type="media_matrix_config",
        target_id=row.id,
        payload={
            "categories": len(payload),
            "items": sum(
                len(section.get("items", []))
                for category in payload
                for section in category.get("sections", [])
            ),
        },
    )
    db.commit()
    db.refresh(row)
    return ok(_config_data(row))


@router.delete("/config", response_model=Envelope[dict])
def reset_config(
    admin: User = Depends(_require_system_admin),
    db: Session = Depends(get_db),
) -> dict:
    """清空自定义配置，公开页回到代码里的默认目录；不回滚历史审计。"""
    row = _get_config(db)
    if row is not None:
        record_audit(
            db,
            project_id=None,
            actor_id=admin.id,
            action="media_matrix.reset",
            target_type="media_matrix_config",
            target_id=row.id,
            payload={},
        )
        db.delete(row)
        db.commit()
    return ok({"payload": None})


__all__ = ["router"]

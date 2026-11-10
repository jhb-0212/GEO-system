"""证据文件访问：先校验项目授权，再做路径包含检查，最后写审计。

文件中转只允许读 evidence_root 之下的路径，storage_key 由服务端生成，
不接受前端传绝对路径，避免路径穿越。
"""

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.core.config import settings
from app.core.errors import PathEscapeError, ResourceMissingError
from app.db.session import get_db
from app.models import EvidenceFile
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(prefix="/api/v1/projects/{project_id}/evidence", tags=["证据文件"])


@router.get("/{evidence_id}/download")
def download_evidence(
    evidence_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("evidence.read")),
    db: Session = Depends(get_db),
) -> FileResponse:
    row = require_scoped_row(db, EvidenceFile, ctx.project.id, resource="evidence", id=evidence_id)

    root = settings.evidence_root.resolve()
    target = (root / row.storage_key).resolve()
    if target != root and root not in target.parents:
        raise PathEscapeError("证据文件路径非法")
    if not target.is_file():
        raise ResourceMissingError("证据文件不存在", code="evidence_missing")

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="evidence.download",
        target_type="evidence_file",
        target_id=row.id,
        payload={"storage_key": row.storage_key, "checksum": row.checksum},
    )
    db.commit()
    return FileResponse(
        target,
        media_type=row.content_type or "application/octet-stream",
        filename=target.name,
    )

"""项目资质：营业执照、办学许可、行业认证等，带有效期与到期提示。

到期状态不落库，读取时按 expires_on 现算，接口统一给 valid / expiring / expired，
前端只负责展示，不在前端重算一遍口径。
"""

import mimetypes
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope
from app.api.responses import ok
from app.core.config import settings
from app.core.errors import AppError, PathEscapeError, ResourceMissingError
from app.db.session import get_db
from app.services.queries import fetch_many
from app.models import Certification
from app.schemas.certification import CertificationCreate, CertificationUpdate
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/certifications",
    tags=["资质"],
    responses=COMMON_ERRORS,
)

EXPIRING_DAYS = 60
# 证据图片只收扫描件/照片常见格式；PDF 走素材库，资质这里不混进来。
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_MAX_BYTES = 8 * 1024 * 1024
_SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),
}


def _matches_signature(suffix: str, head: bytes) -> bool:
    return any(head.startswith(sig) for sig in _SIGNATURES.get(suffix, ()))


def _safe_name(filename: str) -> str:
    base = Path(filename).name.strip() or "evidence"
    return base[:255]


def _status(expires_on: date | None) -> tuple[str | None, int | None]:
    if expires_on is None:
        return None, None
    days_left = (expires_on - date.today()).days
    if days_left < 0:
        return "expired", days_left
    if days_left <= EXPIRING_DAYS:
        return "expiring", days_left
    return "valid", days_left


def _serialize(row: Certification) -> dict:
    status, days_left = _status(row.expires_on)
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "name": row.name,
        "category": row.category,
        "issuer": row.issuer,
        "cert_no": row.cert_no,
        "issued_on": row.issued_on,
        "expires_on": row.expires_on,
        "status": status,
        "days_left": days_left,
        "evidence_url": row.evidence_url,
        "evidence_image_url": (
            f"/api/v1/projects/{row.project_id}/certifications/{row.id}/evidence-image"
            if row.evidence_image_key
            else None
        ),
        "evidence_image_name": row.evidence_image_name,
        "notes": row.notes,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("", response_model=Envelope[list])
def list_certifications(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    include_inactive: bool = False,
) -> dict:
    filters = [Certification.project_id == ctx.project.id]
    if not include_inactive:
        filters.append(Certification.is_active.is_(True))
    rows = fetch_many(
        db,
        Certification,
        filters,
        order_by=(
            Certification.expires_on.asc().nullslast(),
            Certification.created_at.desc(),
        ),
    )
    return ok([_serialize(row) for row in rows])


@router.post("", status_code=201, response_model=Envelope[dict])
def create_certification(
    payload: CertificationCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    if payload.issued_on and payload.expires_on and payload.expires_on < payload.issued_on:
        raise AppError("到期日不能早于发证日", code="certification_date_invalid")
    row = Certification(
        project_id=ctx.project.id,
        created_by=ctx.user.id,
        **payload.model_dump(),
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="certification.create",
        target_type="certification",
        target_id=row.id,
        payload={"name": row.name},
    )
    db.commit()
    return ok(_serialize(row))


@router.patch("/{certification_id}", response_model=Envelope[dict])
def update_certification(
    certification_id: uuid.UUID,
    payload: CertificationUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Certification, ctx.project.id, resource="certification", id=certification_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise AppError("没有需要更新的字段", code="empty_update")
    issued = changes.get("issued_on", row.issued_on)
    expires = changes.get("expires_on", row.expires_on)
    if issued and expires and expires < issued:
        raise AppError("到期日不能早于发证日", code="certification_date_invalid")
    for field, value in changes.items():
        setattr(row, field, value)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="certification.update",
        target_type="certification",
        target_id=row.id,
        payload={"fields": sorted(changes)},
    )
    db.commit()
    return ok(_serialize(row))


@router.post("/{certification_id}/evidence-image", status_code=201, response_model=Envelope[dict])
async def upload_evidence_image(
    certification_id: uuid.UUID,
    file: UploadFile = File(...),
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    """上传资质证据图片（扫描件/拍照）。

    只收 png/jpg/webp，靠文件头校验而不是扩展名；旧的图片先删除再落新图，
    避免同一资质留下多个孤儿文件。
    """

    row = require_scoped_row(db, Certification, ctx.project.id, resource="certification", id=certification_id)
    filename = _safe_name(file.filename or "evidence")
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise AppError("证据图片只支持 png/jpg/webp", code="certification_image_type_invalid")

    head = await file.read(16)
    await file.seek(0)
    if not _matches_signature(suffix, head):
        await file.close()
        raise AppError("图片内容与扩展名不一致，已拒绝上传", code="certification_image_mismatch")

    root = settings.evidence_root.resolve()
    relative = Path("certifications") / str(ctx.project.id) / f"{uuid.uuid4().hex}{suffix}"
    target = (root / relative).resolve()
    if root not in target.parents:
        await file.close()
        raise PathEscapeError("图片路径非法")
    target.parent.mkdir(parents=True, exist_ok=True)

    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > IMAGE_MAX_BYTES:
                    raise AppError("证据图片超过 8MB 上限", code="certification_image_too_large")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    previous = row.evidence_image_key
    row.evidence_image_key = relative.as_posix()
    row.evidence_image_name = filename
    if previous:
        (root / previous).unlink(missing_ok=True)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="certification.evidence_image_upload",
        target_type="certification",
        target_id=row.id,
        payload={"file_name": filename, "byte_size": size},
    )
    db.commit()
    return ok(_serialize(row))


@router.get(
    "/{certification_id}/evidence-image",
    responses={
        200: {
            "description": "证据图片二进制流",
            "content": {"image/*": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def read_evidence_image(
    certification_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> FileResponse:
    row = require_scoped_row(db, Certification, ctx.project.id, resource="certification", id=certification_id)
    if not row.evidence_image_key:
        raise ResourceMissingError("该资质还没有上传证据图片", code="certification_image_missing")
    root = settings.evidence_root.resolve()
    target = (root / row.evidence_image_key).resolve()
    if root not in target.parents:
        raise PathEscapeError("图片路径非法")
    if not target.is_file():
        raise ResourceMissingError("证据图片文件不存在", code="certification_image_missing")
    return FileResponse(
        target,
        media_type=mimetypes.guess_type(row.evidence_image_name or row.evidence_image_key)[0] or "image/png",
        filename=row.evidence_image_name,
    )


@router.delete("/{certification_id}/evidence-image", response_model=Envelope[dict])
def delete_evidence_image(
    certification_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Certification, ctx.project.id, resource="certification", id=certification_id)
    key = row.evidence_image_key
    row.evidence_image_key = None
    row.evidence_image_name = None
    if key:
        (settings.evidence_root.resolve() / key).unlink(missing_ok=True)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="certification.evidence_image_delete",
        target_type="certification",
        target_id=row.id,
        payload={"storage_key": key},
    )
    db.commit()
    return ok(_serialize(row))


@router.delete("/{certification_id}", response_model=Envelope[dict])
def delete_certification(
    certification_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Certification, ctx.project.id, resource="certification", id=certification_id)
    image_key = row.evidence_image_key
    db.delete(row)
    if image_key:
        (settings.evidence_root.resolve() / image_key).unlink(missing_ok=True)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="certification.delete",
        target_type="certification",
        target_id=certification_id,
        payload={"name": row.name},
    )
    db.commit()
    return ok({"id": str(certification_id), "deleted": True})
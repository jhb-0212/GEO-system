"""素材库：元数据 CRUD 与文件上传/下载。

文件本体落 evidence_root/materials/{project_id}/，storage_key 由服务端生成；
不接受前端传路径，不允许把可执行文件放进素材库。
"""

import hashlib
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    MaterialData,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.config import settings
from app.core.errors import AppError, PathEscapeError, ResourceMissingError
from app.db.session import get_db
from app.models import Material
from app.models.enums import MaterialCategory
from app.schemas import MaterialUpdate
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/materials",
    tags=["素材库"],
    responses=COMMON_ERRORS,
)

ALLOWED_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".pdf",
    ".doc",
    ".docx",
    ".txt",
    ".md",
    ".csv",
    ".zip",
}
MAX_BYTES = 20 * 1024 * 1024
SIGNATURE_BYTES = 8192


def _matches_signature(suffix: str, head: bytes) -> bool:
    """按文件头判断扩展名是否可信；文本类不做内容嗅探。"""
    if suffix == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    if suffix == ".gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if suffix == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if suffix == ".pdf":
        return b"%PDF-" in head[:1024]
    if suffix in {".zip", ".docx"}:
        return head.startswith(b"PK\x03\x04")
    if suffix == ".doc":
        return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    # txt / md / csv 是文本，无法也不应靠魔数判断；仍受大小和下载附件语义约束。
    return True


def _serialize(row: Material) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "title": row.title,
        "category": row.category,
        "description": row.description,
        "file_name": row.file_name,
        "content_type": row.content_type,
        "byte_size": row.byte_size,
        "checksum": row.checksum,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _safe_name(name: str | None) -> str:
    clean = Path(name or "file").name.strip()
    return clean[:255] or "file"


@router.get("", response_model=PagedEnvelope[MaterialData])
def list_materials(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
    category: MaterialCategory | None = Query(default=None, description="按分类筛选"),
) -> dict:
    base = select(Material).where(Material.project_id == ctx.project.id)
    if category is not None:
        base = base.where(Material.category == category)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Material.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page([_serialize(row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("", status_code=201, response_model=Envelope[MaterialData])
async def upload_material(
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
    title: str = Form(...),
    category: MaterialCategory = Form(MaterialCategory.DOCUMENT),
    description: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> dict:
    clean_title = title.strip()
    if not clean_title:
        raise AppError("素材标题不能为空", code="material_title_required")
    if len(clean_title) > 255:
        raise AppError("素材标题不能超过 255 字", code="material_title_too_long")
    clean_description = description.strip() if description and description.strip() else None
    if clean_description and len(clean_description) > 5000:
        raise AppError("素材说明不能超过 5000 字", code="material_description_too_long")
    filename = _safe_name(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise AppError(
            "不支持的文件类型，仅允许图片、PDF、Office 文档、文本或 zip",
            code="material_type_not_allowed",
        )

    root = settings.evidence_root.resolve()
    head = await file.read(SIGNATURE_BYTES)
    await file.seek(0)
    if not _matches_signature(suffix, head):
        await file.close()
        raise AppError(
            "文件内容与扩展名不一致，已拒绝上传",
            code="material_content_mismatch",
        )

    relative = Path("materials") / str(ctx.project.id) / f"{uuid.uuid4().hex}{suffix}"
    target = (root / relative).resolve()
    if root not in target.parents:
        raise PathEscapeError("素材路径非法")
    target.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise AppError("文件超过 20MB 上限", code="material_too_large")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    row = Material(
        project_id=ctx.project.id,
        title=clean_title,
        category=category,
        description=clean_description,
        file_name=filename,
        content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        byte_size=size,
        checksum=digest.hexdigest(),
        storage_key=relative.as_posix(),
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="material.upload",
        target_type="material",
        target_id=row.id,
        payload={"file_name": filename, "byte_size": size, "checksum": row.checksum},
    )
    db.commit()
    return ok(_serialize(row))


@router.patch("/{material_id}", response_model=Envelope[MaterialData])
def update_material(
    material_id: uuid.UUID,
    payload: MaterialUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    row = require_scoped_row(db, Material, ctx.project.id, resource="material", id=material_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise AppError("没有需要更新的字段", code="empty_update")
    for field, value in changes.items():
        setattr(row, field, value)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="material.update",
        target_type="material",
        target_id=row.id,
        payload={"fields": sorted(changes)},
    )
    db.commit()
    return ok(_serialize(row))


@router.get(
    "/{material_id}/download",
    responses={
        200: {
            "description": "素材文件二进制流",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def download_material(
    material_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> FileResponse:
    row = require_scoped_row(db, Material, ctx.project.id, resource="material", id=material_id)
    root = settings.evidence_root.resolve()
    target = (root / row.storage_key).resolve()
    if root not in target.parents:
        raise PathEscapeError("素材路径非法")
    if not target.is_file():
        raise ResourceMissingError("素材文件不存在", code="material_missing")
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="material.download",
        target_type="material",
        target_id=row.id,
        payload={"storage_key": row.storage_key},
    )
    db.commit()
    return FileResponse(
        target,
        media_type=mimetypes.guess_type(row.file_name)[0] or "application/octet-stream",
        filename=row.file_name,
    )

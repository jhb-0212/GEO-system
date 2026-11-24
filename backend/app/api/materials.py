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
from app.services.queries import page_of

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
    ".mp4",
    ".mov",
    ".pdf",
    ".doc",
    ".docx",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".html",
    ".htm",
    ".zip",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".mov"}
MAX_BYTES = 20 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024
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
    if suffix in VIDEO_SUFFIXES:
        # MP4 / MOV 同属 ISO BMFF：第 4–8 字节是 'ftyp' 盒标识。
        return head[4:8] == b"ftyp"
    if suffix == ".pdf":
        return b"%PDF-" in head[:1024]
    if suffix in {".zip", ".docx", ".pptx"}:
        return head.startswith(b"PK\x03\x04")
    if suffix == ".doc":
        return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    # txt / md / csv / html 是文本，无法也不应靠魔数判断；仍受大小和下载附件语义约束。
    return True


def _serialize(row: Material) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "title": row.title,
        "category": row.category,
        "group_name": row.group_name,
        "sort_order": row.sort_order,
        "source": row.source,
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
    group_name: str | None = Query(default=None, max_length=120, description="按分组筛选"),
) -> dict:
    filters = [Material.project_id == ctx.project.id]
    if category is not None:
        filters.append(Material.category == category)
    if group_name:
        filters.append(Material.group_name == group_name.strip())
    total, rows = page_of(
        db,
        Material,
        filters,
        order_by=(Material.sort_order.asc(), Material.created_at.desc()),
        page=page,
        page_size=page_size,
    )
    return ok_page([_serialize(row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("", status_code=201, response_model=Envelope[MaterialData])
async def upload_material(
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
    title: str = Form(...),
    category: MaterialCategory = Form(MaterialCategory.DOCUMENT),
    description: str | None = Form(default=None),
    group_name: str | None = Form(default=None),
    source: str | None = Form(default=None),
    sort_order: int = Form(default=0),
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
    clean_group = group_name.strip() if group_name and group_name.strip() else None
    if clean_group and len(clean_group) > 120:
        raise AppError("分组名不能超过 120 字", code="material_group_too_long")
    clean_source = source.strip() if source and source.strip() else None
    if clean_source and len(clean_source) > 64:
        raise AppError("来源标签不能超过 64 字", code="material_source_too_long")
    if sort_order < 0 or sort_order > 100000:
        raise AppError("排序值应在 0–100000 之间", code="material_sort_invalid")
    filename = _safe_name(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise AppError(
            "不支持的文件类型，仅允许图片、视频、PDF、Office 文档、文本或 zip",
            code="material_type_not_allowed",
        )
    # 分类与后缀必须自洽：图片栏只收图片，视频栏只收成片，避免素材页分组错位。
    if category == MaterialCategory.IMAGE and suffix not in IMAGE_SUFFIXES:
        raise AppError("「图片」分类只能上传 png/jpg/webp/gif", code="material_category_mismatch")
    if category == MaterialCategory.VIDEO and suffix not in VIDEO_SUFFIXES:
        raise AppError("「视频」分类只能上传 mp4/mov", code="material_category_mismatch")
    if category == MaterialCategory.CASE and suffix in VIDEO_SUFFIXES:
        raise AppError("视频请归到「视频」分类", code="material_category_mismatch")

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

    limit = MAX_VIDEO_BYTES if suffix in VIDEO_SUFFIXES else MAX_BYTES
    limit_label = "100MB" if suffix in VIDEO_SUFFIXES else "20MB"

    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise AppError(f"文件超过 {limit_label} 上限", code="material_too_large")
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
        group_name=clean_group,
        source=clean_source,
        sort_order=sort_order,
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


@router.delete("/{material_id}", response_model=Envelope[dict])
def delete_material(
    material_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
    purge_file: bool = Query(default=True, description="同时删除服务器上的原文件"),
) -> dict:
    """删除素材：先删行再删文件，文件缺失不阻断（历史上可能已被清理）。"""
    row = require_scoped_row(db, Material, ctx.project.id, resource="material", id=material_id)
    file_name = row.file_name
    storage_key = row.storage_key
    db.delete(row)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="material.delete",
        target_type="material",
        target_id=material_id,
        payload={"file_name": file_name, "storage_key": storage_key, "purge_file": purge_file},
    )
    db.commit()
    if purge_file:
        root = settings.evidence_root.resolve()
        target = (root / storage_key).resolve()
        if root in target.parents:
            target.unlink(missing_ok=True)
    return ok({"id": str(material_id), "deleted": True, "purge_file": purge_file})


@router.get(
    "/{material_id}/preview",
    responses={
        200: {
            "description": "图片/视频内联预览流（不触发下载审计）",
            "content": {"*/*": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def preview_material(
    material_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> FileResponse:
    """素材页缩略预览：只放行图片与视频，返回 inline 而非 attachment。

    预览是浏览行为，不写 material.download 审计——列表里滚动就会触发上百条，
    真正取走原文件仍走 download 并留痕。
    """
    row = require_scoped_row(db, Material, ctx.project.id, resource="material", id=material_id)
    media_type = mimetypes.guess_type(row.file_name)[0] or ""
    if not (media_type.startswith("image/") or media_type.startswith("video/")):
        raise AppError("该素材不支持预览，请下载原文件", code="material_preview_unsupported")
    root = settings.evidence_root.resolve()
    target = (root / row.storage_key).resolve()
    if root not in target.parents:
        raise PathEscapeError("素材路径非法")
    if not target.is_file():
        raise ResourceMissingError("素材文件不存在", code="material_missing")
    return FileResponse(
        target,
        media_type=media_type,
        filename=row.file_name,
        content_disposition_type="inline",
    )

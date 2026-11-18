"""证据文件访问：上传先校验项目/样本授权，下载再做路径包含检查，最后写审计。

文件中转只允许读写 evidence_root 之下的路径，storage_key 由服务端生成，
不接受前端传绝对路径，避免路径穿越。
"""

import hashlib
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_any_permission, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, EvidenceUploaded, ok
from app.core.config import settings
from app.core.errors import AppError, PathEscapeError, ResourceMissingError
from app.db.session import get_db
from app.models import EvidenceFile, MonitoringSample
from app.models.enums import EvidenceFileType
from app.services.audit import record_audit
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/evidence",
    tags=["证据文件"],
    responses=COMMON_ERRORS,
)

ALLOWED_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".pdf",
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
    if suffix == ".zip":
        return head.startswith(b"PK\x03\x04")
    # txt / md / csv 是文本，无法也不应靠魔数判断；仍受大小和下载附件语义约束。
    return True


def _safe_name(name: str | None) -> str:
    clean = Path(name or "file").name.strip()
    return clean[:255] or "file"


@router.post("", status_code=201, response_model=Envelope[EvidenceUploaded])
async def upload_evidence(
    sample_id: uuid.UUID = Form(...),
    file_type: EvidenceFileType = Form(EvidenceFileType.SCREENSHOT),
    file: UploadFile = File(...),
    ctx: ProjectContext = Depends(require_any_permission("monitoring.execute", "evidence.review")),
    db: Session = Depends(get_db),
) -> dict:
    """给手测/自动样本补截图或原始文件；只落元信息，文件本体在 evidence_root。"""
    sample = require_scoped_row(
        db,
        MonitoringSample,
        ctx.project.id,
        resource="monitoring_sample",
        id=sample_id,
    )
    filename = _safe_name(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise AppError(
            "不支持的文件类型，仅允许图片、PDF、文本或 zip",
            code="evidence_type_not_allowed",
        )

    root = settings.evidence_root.resolve()
    head = await file.read(SIGNATURE_BYTES)
    await file.seek(0)
    if not _matches_signature(suffix, head):
        await file.close()
        raise AppError(
            "文件内容与扩展名不一致，已拒绝上传",
            code="evidence_content_mismatch",
        )

    relative = (
        Path("evidence")
        / str(ctx.project.id)
        / str(sample.id)
        / f"{uuid.uuid4().hex}{suffix}"
    )
    target = (root / relative).resolve()
    if root not in target.parents:
        raise PathEscapeError("证据文件路径非法")
    target.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise AppError("文件超过 20MB 上限", code="evidence_too_large")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    row = EvidenceFile(
        project_id=ctx.project.id,
        sample_id=sample.id,
        storage_key=relative.as_posix(),
        file_type=file_type,
        checksum=digest.hexdigest(),
        byte_size=size,
        content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="evidence.upload",
        target_type="evidence_file",
        target_id=row.id,
        payload={
            "sample_id": str(sample.id),
            "file_name": filename,
            "file_type": file_type.value,
            "byte_size": size,
            "checksum": row.checksum,
        },
    )
    db.commit()
    return ok(
        {
            "evidence_id": str(row.id),
            "sample_id": str(sample.id),
            "file_type": row.file_type.value,
            "content_type": row.content_type,
            "byte_size": size,
            "checksum": row.checksum,
        }
    )


@router.get(
    "/{evidence_id}/download",
    responses={
        200: {
            "description": "证据文件二进制流",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
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

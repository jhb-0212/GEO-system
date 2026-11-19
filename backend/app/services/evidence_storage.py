"""证据文件二进制存储：本地 evidence_root 或 S3 兼容对象存储。

数据库只存 storage_key，不存绝对路径。S3 未配置时保持本地开发路径，
配置 `S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY / S3_BUCKET` 后自动切到对象存储。
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.errors import AppError, PathEscapeError, ResourceMissingError

MAX_BYTES = 20 * 1024 * 1024
CHUNK = 1024 * 1024


def s3_enabled() -> bool:
    """四个关键配置齐全才启用 S3；缺一项就回退本地，避免半配置写入失败。"""
    return all(
        value.strip()
        for value in (
            settings.s3_endpoint,
            settings.s3_access_key,
            settings.s3_secret_key,
            settings.s3_bucket,
        )
    )


def backend_name() -> str:
    return "s3" if s3_enabled() else "local"


def _s3_client():
    # 延迟导入：未配置 S3 的部署不需要加载 boto3。
    import boto3
    from botocore.config import Config

    endpoint = settings.s3_endpoint.strip()
    use_ssl = settings.s3_secure or endpoint.startswith("https://")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key.strip(),
        aws_secret_access_key=settings.s3_secret_key.strip(),
        region_name=settings.s3_region.strip() or "us-east-1",
        use_ssl=use_ssl,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _ensure_bucket(client) -> None:
    """本地 MinIO 第一次上传时自动建桶；已有桶则直接返回。"""
    from botocore.exceptions import ClientError

    bucket = settings.s3_bucket.strip()
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError:
        pass
    try:
        create_kwargs = {"Bucket": bucket}
        region = settings.s3_region.strip()
        if region and region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        client.create_bucket(**create_kwargs)
    except ClientError as exc:
        raise AppError("证据存储桶不可用", code="evidence_storage_bucket_unavailable") from exc


def _validate_key(key: str) -> str:
    clean = key.replace("\\", "/").strip("/")
    if not clean or clean.startswith("/") or ".." in Path(clean).parts:
        raise PathEscapeError("证据文件路径非法")
    return clean


def _local_target(key: str) -> Path:
    root = settings.evidence_root.resolve()
    target = (root / _validate_key(key)).resolve()
    if target != root and root not in target.parents:
        raise PathEscapeError("证据文件路径非法")
    return target


async def save_upload(file: UploadFile, key: str, content_type: str | None = None) -> tuple[str, int]:
    """把上传流写入本地或 S3，返回 sha256 与字节数。"""
    clean_key = _validate_key(key)
    if s3_enabled():
        digest = hashlib.sha256()
        body = bytearray()
        while chunk := await file.read(CHUNK):
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise AppError("文件超过 20MB 上限", code="evidence_too_large")
            digest.update(chunk)
        client = _s3_client()
        _ensure_bucket(client)
        try:
            client.put_object(
                Bucket=settings.s3_bucket.strip(),
                Key=clean_key,
                Body=bytes(body),
                ContentType=content_type or "application/octet-stream",
            )
        except Exception as exc:  # boto3 的异常类型多，统一转成可读错误
            raise AppError("证据文件写入对象存储失败", code="evidence_storage_write_failed") from exc
        return digest.hexdigest(), len(body)

    target = _local_target(clean_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise AppError("文件超过 20MB 上限", code="evidence_too_large")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), size


def read_bytes(key: str) -> bytes:
    clean_key = _validate_key(key)
    if s3_enabled():
        from botocore.exceptions import ClientError

        client = _s3_client()
        try:
            response = client.get_object(Bucket=settings.s3_bucket.strip(), Key=clean_key)
            return response["Body"].read()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise ResourceMissingError("证据文件不存在", code="evidence_missing") from exc
            raise AppError("证据文件读取对象存储失败", code="evidence_storage_read_failed") from exc
        except Exception as exc:
            raise AppError("证据文件读取对象存储失败", code="evidence_storage_read_failed") from exc

    target = _local_target(clean_key)
    if not target.is_file():
        raise ResourceMissingError("证据文件不存在", code="evidence_missing")
    return target.read_bytes()


def local_path(key: str) -> Path:
    """仅本地后端使用；S3 后端调用会抛错，避免误把对象键当本地路径。"""
    if s3_enabled():
        raise AppError("当前使用对象存储，不能返回本地路径", code="evidence_storage_not_local")
    target = _local_target(key)
    if not target.is_file():
        raise ResourceMissingError("证据文件不存在", code="evidence_missing")
    return target


def guess_content_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"

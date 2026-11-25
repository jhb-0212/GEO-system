"""只读 API Key 生成、校验、限流与序列化。"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import ApiKey
from app.services.rate_limit import IpWindowLimiter

READ_SCOPES = {
    "read:overview": "项目总览与本轮统计",
    "read:questions": "问题清单与版本",
    "read:monitoring": "监测样本（不含原始回答全文）",
    "read:opportunities": "机会与建议",
}

_limiters: dict[str, IpWindowLimiter] = {}


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_api_key(db: Session, project_id: uuid.UUID, *, name: str, scopes: list[str], rate_limit_per_minute: int, created_by=None, expires_at: datetime | None = None) -> tuple[ApiKey, str]:
    unknown = set(scopes) - set(READ_SCOPES)
    if unknown:
        raise AppError(f"未知 scope：{','.join(sorted(unknown))}", code="api_key_scope_invalid")
    if not scopes:
        raise AppError("至少选择一个 scope", code="api_key_scope_required")
    raw = f"geo_pk_{secrets.token_urlsafe(32)}"
    row = ApiKey(
        project_id=project_id, name=name, key_prefix=raw[:14], key_hash=hash_key(raw),
        scopes=scopes, rate_limit_per_minute=rate_limit_per_minute, is_active=True,
        created_by=created_by, expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    return row, raw


def authenticate(db: Session, raw: str, *, required_scope: str) -> ApiKey:
    if not raw.startswith("geo_pk_"):
        raise AppError("API Key 格式无效", code="api_key_invalid")
    row = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(raw)))
    if row is None or not row.is_active or row.revoked_at is not None:
        raise AppError("API Key 无效或已撤销", code="api_key_invalid")
    if row.expires_at is not None and row.expires_at <= datetime.now(timezone.utc):
        raise AppError("API Key 已过期", code="api_key_expired")
    if required_scope not in (row.scopes or []):
        raise AppError("该 Key 未开通此 scope", code="api_key_scope_denied")
    limiter = _limiters.get(str(row.id))
    if limiter is None:
        limiter = IpWindowLimiter(namespace=f"api_key:{row.id}", per_minute=row.rate_limit_per_minute)
        _limiters[str(row.id)] = limiter
    limiter.per_minute = row.rate_limit_per_minute
    if not limiter.consume(str(row.id)):
        raise AppError("API Key 请求过于频繁", code="api_key_rate_limited")
    row.last_used_at = datetime.now(timezone.utc)
    db.flush()
    return row


def revoke_api_key(db: Session, row: ApiKey) -> ApiKey:
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        row.is_active = False
        db.flush()
    return row


def key_payload(row: ApiKey) -> dict:
    return {
        "id": str(row.id), "name": row.name, "key_prefix": row.key_prefix,
        "scopes": row.scopes, "rate_limit_per_minute": row.rate_limit_per_minute,
        "is_active": row.is_active,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }

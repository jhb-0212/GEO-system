"""月报只读分享：令牌、密码、白标、有效期与吊销。

安全边界：
- 分享令牌只以 SHA-256 哈希落库，数据库泄露也拿不到可用的链接；
- 仅允许分享冻结月报快照，分享内容不会随后台实时数据变化；
- 无效、过期、吊销的令牌统一返回同一句“不可用”，不区分原因；
- 密码只存 bcrypt 哈希，校验失败不返回报告正文。
"""

from __future__ import annotations

import copy
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    BusinessValidationError,
    ConflictError,
    ResourceMissingError,
    UnauthorizedError,
)
from app.core.security import hash_password, verify_password
from app.models import MonthlyReportSnapshot, Project, ReportShare
from app.services.url_policy import validate_public_http_url
from app.services.branding import organization_branding

SHARE_TOKEN_BYTES = 32
MAX_ACTIVE_SHARES_PER_SNAPSHOT = 20
MAX_SHARE_DAYS = 365
DEFAULT_SHARE_DAYS = 30
_ACCENT_PATTERN = "#2563eb"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status(row: ReportShare, now: datetime) -> str:
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at <= now:
        return "expired"
    return "active"


def _share_status_payload(row: ReportShare, *, month: str | None = None) -> dict[str, Any]:
    now = _now()
    return {
        "share_id": str(row.id),
        "project_id": str(row.project_id),
        "snapshot_id": str(row.snapshot_id),
        "month": month,
        "label": row.label,
        "brand_name": row.brand_name,
        "brand_logo_url": row.brand_logo_url,
        "accent_color": row.accent_color,
        "contact_text": row.contact_text,
        "show_leads": row.show_leads,
        "password_enabled": row.password_hash is not None,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "view_count": row.view_count,
        "last_viewed_at": row.last_viewed_at,
        "created_at": row.created_at,
        "status": _status(row, now),
        "share_path": None,
    }


def _valid_share(db: Session, token: str) -> tuple[ReportShare, MonthlyReportSnapshot]:
    if not token or len(token) > 128:
        raise ResourceMissingError("分享链接不可用", code="report_share_unavailable")
    row = db.scalar(select(ReportShare).where(ReportShare.token_hash == _token_hash(token)))
    if row is None:
        raise ResourceMissingError("分享链接不可用", code="report_share_unavailable")
    now = _now()
    if row.revoked_at is not None or row.expires_at <= now:
        raise ResourceMissingError("分享链接不可用", code="report_share_unavailable")
    snapshot = db.scalar(
        select(MonthlyReportSnapshot).where(
            MonthlyReportSnapshot.id == row.snapshot_id,
            MonthlyReportSnapshot.project_id == row.project_id,
        )
    )
    if snapshot is None:
        raise ResourceMissingError("分享链接不可用", code="report_share_unavailable")
    return row, snapshot


def create_report_share(
    db: Session,
    *,
    project: Project,
    snapshot_id: uuid.UUID,
    actor_id: uuid.UUID,
    label: str | None = None,
    password: str | None = None,
    expires_in_days: int = DEFAULT_SHARE_DAYS,
    brand_name: str | None = None,
    brand_logo_url: str | None = None,
    accent_color: str = _ACCENT_PATTERN,
    contact_text: str | None = None,
    show_leads: bool = False,
) -> tuple[ReportShare, str]:
    snapshot = db.scalar(
        select(MonthlyReportSnapshot).where(
            MonthlyReportSnapshot.id == snapshot_id,
            MonthlyReportSnapshot.project_id == project.id,
        )
    )
    if snapshot is None:
        raise ResourceMissingError("月报快照不存在或不属于当前项目", code="monthly_snapshot_missing")

    now = _now()
    active_count = int(
        db.scalar(
            select(func.count())
            .select_from(ReportShare)
            .where(
                ReportShare.project_id == project.id,
                ReportShare.snapshot_id == snapshot_id,
                ReportShare.revoked_at.is_(None),
                ReportShare.expires_at > now,
            )
        )
        or 0
    )
    if active_count >= MAX_ACTIVE_SHARES_PER_SNAPSHOT:
        raise ConflictError(
            f"同一月报最多同时保留 {MAX_ACTIVE_SHARES_PER_SNAPSHOT} 个有效分享链接，请先吊销旧链接",
            code="report_share_limit_reached",
        )

    days = max(1, min(MAX_SHARE_DAYS, int(expires_in_days)))
    clean_brand = (brand_name or "").strip() or None
    clean_label = (label or "").strip() or None
    clean_contact = (contact_text or "").strip() or None
    logo = validate_public_http_url(brand_logo_url, field_name="品牌 Logo 地址")
    color = (accent_color or _ACCENT_PATTERN).strip().lower()
    if len(color) != 7 or not color.startswith("#"):
        raise BusinessValidationError("主色必须是 #RRGGBB 格式", code="invalid_accent_color")
    try:
        int(color[1:], 16)
    except ValueError as exc:
        raise BusinessValidationError("主色必须是 #RRGGBB 格式", code="invalid_accent_color") from exc

    if password and len(password.encode("utf-8")) > 72:
        raise BusinessValidationError("密码不能超过 72 字节", code="report_password_too_long")

    token = secrets.token_urlsafe(SHARE_TOKEN_BYTES)
    row = ReportShare(
        project_id=project.id,
        snapshot_id=snapshot.id,
        token_hash=_token_hash(token),
        label=clean_label,
        password_hash=hash_password(password) if password else None,
        brand_name=clean_brand,
        brand_logo_url=logo,
        accent_color=color,
        contact_text=clean_contact,
        show_leads=bool(show_leads),
        expires_at=now + timedelta(days=days),
        created_by=actor_id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("分享链接生成冲突，请重试", code="report_share_conflict") from exc
    return row, token


def list_report_shares(
    db: Session,
    *,
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conditions = [ReportShare.project_id == project_id]
    if snapshot_id is not None:
        conditions.append(ReportShare.snapshot_id == snapshot_id)
    rows = db.execute(
        select(ReportShare, MonthlyReportSnapshot.month)
        .join(MonthlyReportSnapshot, MonthlyReportSnapshot.id == ReportShare.snapshot_id)
        .where(*conditions)
        .order_by(ReportShare.created_at.desc(), ReportShare.id)
        .limit(max(1, min(100, limit)))
    ).all()
    return [_share_status_payload(row, month=month) for row, month in rows]


def revoke_report_share(
    db: Session,
    *,
    project_id: uuid.UUID,
    share_id: uuid.UUID,
) -> dict[str, Any]:
    row = db.scalar(
        select(ReportShare)
        .where(ReportShare.project_id == project_id, ReportShare.id == share_id)
        .with_for_update()
    )
    if row is None:
        raise ResourceMissingError("分享链接不存在", code="report_share_missing")
    if row.revoked_at is not None:
        raise ConflictError("分享链接已经吊销", code="report_share_already_revoked")
    row.revoked_at = _now()
    db.flush()
    snapshot_month = db.scalar(
        select(MonthlyReportSnapshot.month).where(MonthlyReportSnapshot.id == row.snapshot_id)
    )
    return _share_status_payload(row, month=snapshot_month)


def public_share_meta(db: Session, token: str) -> dict[str, Any]:
    row, snapshot = _valid_share(db, token)
    report = snapshot.report or {}
    branding = organization_branding(db, row.project_id)
    return {
        "brand_name": row.brand_name or branding.get("product_name") or _project_name(db, row.project_id),
        "brand_logo_url": row.brand_logo_url or branding.get("logo_url"),
        "accent_color": row.accent_color or branding.get("accent_color"),
        "contact_text": row.contact_text,
        "month": snapshot.month,
        "period_start": report.get("period_start"),
        "period_end": report.get("period_end"),
        "captured_at": snapshot.captured_at,
        "requires_password": row.password_hash is not None,
        "expires_at": row.expires_at,
    }


def _project_name(db: Session, project_id: uuid.UUID) -> str:
    name = db.scalar(select(Project.name).where(Project.id == project_id))
    return str(name or "项目报告")


def public_share_payload(db: Session, *, token: str, password: str | None = None) -> dict[str, Any]:
    row, snapshot = _valid_share(db, token)
    if row.password_hash is not None:
        if not password:
            raise UnauthorizedError("该报告需要访问密码", code="report_password_required")
        if not verify_password(password, row.password_hash):
            raise UnauthorizedError("访问密码不正确", code="report_password_invalid")

    report = copy.deepcopy(snapshot.report or {})
    if not row.show_leads:
        report["leads"] = None
    now = _now()
    row.view_count = int(row.view_count or 0) + 1
    row.last_viewed_at = now
    db.flush()

    branding = organization_branding(db, row.project_id)
    return {
        "brand_name": row.brand_name or branding.get("product_name") or _project_name(db, row.project_id),
        "brand_logo_url": row.brand_logo_url or branding.get("logo_url"),
        "accent_color": row.accent_color or branding.get("accent_color"),
        "contact_text": row.contact_text,
        "month": snapshot.month,
        "period_start": report.get("period_start"),
        "period_end": report.get("period_end"),
        "captured_at": snapshot.captured_at,
        "expires_at": row.expires_at,
        "snapshot_hash": snapshot.snapshot_hash,
        "report": report,
        "view_count": row.view_count,
    }

"""客户主体（organizations）：列、建、改名。

客户是项目之上的一层边界：配额、名册、继承与客户策略都挂在它上面。
这里只做主体管理，不代替项目成员的授权。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_system_permission
from app.core.config import settings as app_settings
from app.api.responses import COMMON_ERRORS, Envelope, ok
from app.core.errors import AppError
from app.db.session import get_db
from app.models import User
from app.models.industry import Organization
from app.services.organization_registry import (
    active_member_counts,
    all_organizations,
    max_project_members,
    organization_by_code,
    organization_payload as _serialize,
    organization_row,
    project_counts,
)
from app.services.organization_settings import get_settings
from app.services import usage_metering

router = APIRouter(prefix="/api/v1/organizations", tags=["客户"], responses=COMMON_ERRORS)


class OrganizationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=128)


class OrganizationRename(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class OrganizationBranding(BaseModel):
    logo_url: str | None = Field(default=None, max_length=500)
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    accent_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    product_name: str | None = Field(default=None, max_length=64)
    support_email: str | None = Field(default=None, max_length=200)
    hide_vendor_brand: bool | None = None
    custom_domain: str | None = Field(default=None, max_length=255)


@router.get("", response_model=Envelope[list[dict]])
def list_organizations(
    q: str | None = Query(default=None, max_length=64, description="按编码/名称模糊搜索"),
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    rows = all_organizations(db, q)
    project_by_org = project_counts(db)
    member_by_org = active_member_counts(db)
    return ok([
        _serialize(row, project_by_org.get(row.id, 0), member_by_org.get(row.id, 0))
        for row in rows
    ])


@router.post("", status_code=201, response_model=Envelope[dict])
def create_organization(
    payload: OrganizationCreate,
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    code = payload.code.strip().lower()
    if organization_by_code(db, code) is not None:
        raise AppError("客户编码已存在", code="organization_code_exists")
    org = Organization(code=code, name=payload.name.strip(), status="active")
    db.add(org)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("客户编码已存在", code="organization_code_exists") from exc
    db.commit()
    return ok(_serialize(org))


@router.get("/overview", response_model=Envelope[dict])
def organizations_overview(
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    """跨客户用量：项目/名册配额与健康度；项目成员配额按项目粒度，这里只给最大值参考。"""
    orgs = all_organizations(db)
    project_by_org = project_counts(db)
    member_by_org = active_member_counts(db)
    max_by_org = max_project_members(db)
    rows = []
    for org in orgs:
        current = get_settings(db, org.id, None)
        alerts = [item for item in current["alerts"] if item["key"] != "project_members"]
        health = "exceeded" if any(item["level"] == "exceeded" for item in alerts) else "warning" if alerts else "ok"
        rows.append({
            **_serialize(org, project_by_org.get(org.id, 0), member_by_org.get(org.id, 0)),
            "max_project_members": max_by_org.get(org.id, 0),
            "quotas": {"projects": current["quotas"]["projects"], "members": current["quotas"]["members"]},
            "alerts": alerts,
            "health": health,
        })
    return ok({"organizations": rows, "webhook_configured": bool(app_settings.quota_alert_webhook)})


@router.get("/{organization_id}/consumption", response_model=Envelope[dict])
def organization_usage(
    organization_id: uuid.UUID,
    start: str | None = Query(None, description="YYYY-MM-DD，默认最近 30 天"),
    end: str | None = Query(None, description="YYYY-MM-DD，含当天"),
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    """客户级消耗汇总：只看用量，不含价格与账单；额度超限只提示不拦截。"""
    organization_row(db, organization_id)
    try:
        return ok(usage_metering.summarize(db, start, end, organization_id=organization_id))
    except ValueError as exc:
        raise AppError(str(exc), code="usage_range_invalid") from exc


@router.get("/{organization_id}/consumption/events", response_model=Envelope[list[dict]])
def organization_usage_events(
    organization_id: uuid.UUID,
    start: str | None = Query(None),
    end: str | None = Query(None),
    metric: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    """客户级消耗明细：让汇总里的数字点得回具体事件。"""
    try:
        return ok(
            usage_metering.events(
                db, start, end, organization_id=organization_id, metric=metric, limit=limit
            )
        )
    except ValueError as exc:
        raise AppError(str(exc), code="usage_range_invalid") from exc


@router.patch("/{organization_id}", response_model=Envelope[dict])
def rename_organization(
    organization_id: uuid.UUID,
    payload: OrganizationRename,
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    org = organization_row(db, organization_id)
    org.name = payload.name.strip()
    db.commit()
    return ok(_serialize(org))


@router.put("/{organization_id}/branding", response_model=Envelope[dict])
def update_branding(
    organization_id: uuid.UUID,
    payload: OrganizationBranding,
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    """白标只作用于客户可见页面：分享报告、微站、登录页；不改系统内部工作台。

    custom_domain 仅登记意愿，不自动接反向代理或签发证书。
    """
    org = organization_row(db, organization_id)
    incoming = payload.model_dump(exclude_none=True)
    if incoming.get("logo_url") and not incoming["logo_url"].startswith(("https://", "http://")):
        raise AppError("logo_url 必须是 http(s) 地址", code="branding_logo_invalid")
    branding = {**(org.branding or {}), **incoming}
    org.branding = branding
    db.commit()
    return ok({"branding": branding, "custom_domain_active": False})

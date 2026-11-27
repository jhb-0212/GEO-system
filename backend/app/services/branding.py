"""客户白标读取：分享报告、登录页都从这里取同一份 branding。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project
from app.models.industry import Organization

PUBLIC_KEYS = ("logo_url", "primary_color", "accent_color", "product_name", "support_email", "hide_vendor_brand")


def organization_branding(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    project = db.scalar(select(Project).where(Project.id == project_id))
    if project is None or project.organization_id is None:
        return {}
    org = db.scalar(select(Organization).where(Organization.id == project.organization_id))
    if org is None:
        return {}
    return {key: (org.branding or {}).get(key) for key in PUBLIC_KEYS if (org.branding or {}).get(key) is not None}

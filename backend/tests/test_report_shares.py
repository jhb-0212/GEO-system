"""月报分享：令牌只返回一次、密码、白标、线索裁剪、过期与吊销。"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AuditLog, ReportShare
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _lead(client, project, actor, name: str) -> None:
    response = client.post(
        f"/api/v1/projects/{project.id}/leads",
        json={
            "contact_name": name,
            "contact_phone": "13800000000",
            "lead_source": "官网",
            "is_valid": True,
        },
        headers=_auth(actor),
    )
    assert response.status_code == 201, response.text


def _freeze(client, project, actor, month: str) -> str:
    response = client.post(
        f"/api/v1/projects/{project.id}/stats/monthly/snapshots",
        params={"month": month},
        headers=_auth(actor),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["snapshot_id"]


def _create_share(client, project, actor, snapshot_id: str, **overrides) -> dict:
    body = {
        "snapshot_id": snapshot_id,
        "label": "客户交付",
        "brand_name": "示例客户",
        "brand_logo_url": "https://example.com/logo.png",
        "accent_color": "#0f766e",
        "contact_text": "如需解读请联系客户成功团队",
        "expires_in_days": 7,
        **overrides,
    }
    response = client.post(
        f"/api/v1/projects/{project.id}/report-shares",
        json=body,
        headers=_auth(actor),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_share_lifecycle_password_branding_and_lead_trimming(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"share-{suffix}")
    admin = user_factory(f"share-admin-{suffix}")
    lead_ops = user_factory(f"share-leads-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, lead_ops, RoleCode.LEAD_OPS)
    _lead(client, project, lead_ops, "分享测试线索")
    snapshot_id = _freeze(client, project, admin, "2026-11")

    share = _create_share(client, project, admin, snapshot_id, password="secret123")
    token = share["token"]
    assert share["password_enabled"] is True
    assert share["share_path"] == f"/share/{token}"
    assert len(token) >= 32

    meta = client.get(f"/api/v1/public/reports/{token}")
    assert meta.status_code == 200, meta.text
    assert meta.json()["data"]["requires_password"] is True
    assert meta.json()["data"]["brand_name"] == "示例客户"
    assert meta.json()["data"]["brand_logo_url"] == "https://example.com/logo.png"

    wrong = client.post(
        f"/api/v1/public/reports/{token}/access",
        json={"password": "wrong-password"},
    )
    assert wrong.status_code == 401, wrong.text
    assert wrong.json()["error"]["code"] == "report_password_invalid"

    access = client.post(
        f"/api/v1/public/reports/{token}/access",
        json={"password": "secret123"},
    )
    assert access.status_code == 200, access.text
    data = access.json()["data"]
    assert data["brand_name"] == "示例客户"
    assert data["accent_color"] == "#0f766e"
    assert data["report"]["leads"] is None
    assert data["view_count"] == 1

    # 同一快照再建一个允许展示线索的链接，正文仍然来自冻结报告。
    visible = _create_share(client, project, admin, snapshot_id, show_leads=True, password=None)
    visible_access = client.post(
        f"/api/v1/public/reports/{visible['token']}/access",
        json={"password": None},
    )
    assert visible_access.status_code == 200, visible_access.text
    assert visible_access.json()["data"]["report"]["leads"]["total"] == 1

    listed = client.get(
        f"/api/v1/projects/{project.id}/report-shares",
        headers=_auth(admin),
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["data"]
    assert len(items) == 2
    assert all("token" not in item for item in items)
    assert all(item["status"] == "active" for item in items)

    revoked = client.post(
        f"/api/v1/projects/{project.id}/report-shares/{share['share_id']}/revoke",
        headers=_auth(admin),
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["data"]["status"] == "revoked"
    blocked = client.post(
        f"/api/v1/public/reports/{token}/access",
        json={"password": "secret123"},
    )
    assert blocked.status_code == 404
    assert blocked.json()["error"]["code"] == "report_share_unavailable"

    audits = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action.in_(["report_share.create", "report_share.revoke"]),
        )
    ).all()
    assert {row.action for row in audits} == {"report_share.create", "report_share.revoke"}
    assert all("token" not in (row.payload or {}) for row in audits)


def test_share_expiry_invalid_token_and_permissions(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"share-edge-{suffix}")
    admin = user_factory(f"share-edge-admin-{suffix}")
    lead_ops = user_factory(f"share-edge-leads-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, lead_ops, RoleCode.LEAD_OPS)
    snapshot_id = _freeze(client, project, admin, "2026-10")
    share = _create_share(client, project, admin, snapshot_id, password=None)

    missing = client.get("/api/v1/public/reports/not-a-real-token")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "report_share_unavailable"

    row = db.scalar(
        select(ReportShare).where(
            ReportShare.token_hash == hashlib.sha256(share["token"].encode("utf-8")).hexdigest()
        )
    )
    assert row is not None
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()

    expired = client.post(
        f"/api/v1/public/reports/{share['token']}/access",
        json={"password": None},
    )
    assert expired.status_code == 404
    assert expired.json()["error"]["code"] == "report_share_unavailable"

    forbidden_create = client.post(
        f"/api/v1/projects/{project.id}/report-shares",
        json={"snapshot_id": snapshot_id},
        headers=_auth(lead_ops),
    )
    assert forbidden_create.status_code == 403
    assert forbidden_create.json()["error"]["code"] == "insufficient_permission"

    forbidden_list = client.get(
        f"/api/v1/projects/{project.id}/report-shares",
        headers=_auth(lead_ops),
    )
    assert forbidden_list.status_code == 403

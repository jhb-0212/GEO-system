"""白标：组织 branding 写入、公开项目品牌接口、分享报告回退。"""

from __future__ import annotations

import uuid

from app.core.security import create_access_token


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_organization_branding_and_public_endpoint(client, project_factory, user_factory):
    admin = user_factory(f"brand-admin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    project = project_factory(f"brand-{uuid.uuid4().hex[:6]}")
    org_id = project.organization_id

    updated = client.put(
        f"/api/v1/organizations/{org_id}/branding",
        json={
            "logo_url": "https://cdn.example.com/logo.png",
            "primary_color": "#1a73e8",
            "accent_color": "#34a853",
            "product_name": "客户 GEO 中心",
            "support_email": "help@example.com",
            "hide_vendor_brand": True,
            "custom_domain": "geo.example.com",
        },
        headers=_auth(admin),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["branding"]["product_name"] == "客户 GEO 中心"
    assert updated.json()["data"]["custom_domain_active"] is False

    shown = client.get(f"/api/v1/public/projects/{project.code}/branding")
    assert shown.status_code == 200, shown.text
    body = shown.json()["data"]
    assert body["branding"]["logo_url"] == "https://cdn.example.com/logo.png"
    assert body["hide_vendor_brand"] is True

    invalid = client.put(
        f"/api/v1/organizations/{org_id}/branding",
        json={"logo_url": "javascript:alert(1)"}, headers=_auth(admin),
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "branding_logo_invalid"

    orgs = client.get("/api/v1/organizations", headers=_auth(admin))
    assert orgs.status_code == 200
    row = next(item for item in orgs.json()["data"] if item["id"] == str(org_id))
    assert row["branding"]["primary_color"] == "#1a73e8"

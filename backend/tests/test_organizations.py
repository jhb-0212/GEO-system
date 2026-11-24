"""客户主体：建客户、列客户、按客户建项目与筛选。"""

import uuid

from app.core.config import settings
from app.core.security import create_access_token


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_create_and_list_organizations(client, user_factory):
    suffix = uuid.uuid4().hex[:6]
    root = user_factory(f"orgapi-root-{suffix}", is_system_admin=True)
    code = f"acme-{suffix}"

    created = client.post(
        "/api/v1/organizations", headers=_auth(root), json={"code": code, "name": "示例客户"}
    )
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["code"] == code and data["name"] == "示例客户"
    assert data["project_count"] == 0 and data["member_count"] == 0

    listed = client.get("/api/v1/organizations", headers=_auth(root)).json()["data"]
    assert any(item["id"] == data["id"] for item in listed)
    assert any(item["code"] == "default-client" for item in listed)

    renamed = client.patch(
        f"/api/v1/organizations/{data['id']}", headers=_auth(root), json={"name": "示例客户（改）"}
    )
    assert renamed.json()["data"]["name"] == "示例客户（改）"


def test_duplicate_organization_code(client, user_factory):
    suffix = uuid.uuid4().hex[:6]
    root = user_factory(f"orgapi-dup-{suffix}", is_system_admin=True)
    body = {"code": f"dup-{suffix}", "name": "重复客户"}
    assert client.post("/api/v1/organizations", headers=_auth(root), json=body).status_code == 201
    second = client.post("/api/v1/organizations", headers=_auth(root), json=body)
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "organization_code_exists"


def test_organization_endpoints_require_system_admin(client, user_factory):
    suffix = uuid.uuid4().hex[:6]
    user = user_factory(f"orgapi-user-{suffix}")
    assert client.get("/api/v1/organizations", headers=_auth(user)).status_code == 403


def test_prod_create_project_requires_organization(client, user_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    root = user_factory(f"orgapi-prod-root-{suffix}", is_system_admin=True)
    monkeypatch.setattr(settings, "app_env", "prod")

    resp = client.post(
        "/api/v1/projects",
        headers=_auth(root),
        json={"code": f"prod-{suffix}", "name": "生产项目"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "organization_required"


def test_create_project_in_chosen_organization(client, user_factory):
    suffix = uuid.uuid4().hex[:6]
    root = user_factory(f"orgapi-p-root-{suffix}", is_system_admin=True)
    org = client.post(
        "/api/v1/organizations", headers=_auth(root),
        json={"code": f"tenant-{suffix}", "name": "第二客户"},
    ).json()["data"]

    created = client.post(
        "/api/v1/projects", headers=_auth(root),
        json={"code": f"t2-{suffix}", "name": "第二客户项目", "organization_id": org["id"]},
    )
    assert created.status_code == 201, created.text
    project = created.json()["data"]
    assert project["organization_id"] == org["id"]
    assert project["organization_name"] == "第二客户"

    filtered = client.get(
        f"/api/v1/projects?organization_id={org['id']}", headers=_auth(root)
    ).json()["data"]
    assert [item["code"] for item in filtered] == [f"t2-{suffix}"]


def test_project_quota_applies_to_chosen_organization(client, user_factory, db):
    suffix = uuid.uuid4().hex[:6]
    root = user_factory(f"orgapi-q-root-{suffix}", is_system_admin=True)
    org = client.post(
        "/api/v1/organizations", headers=_auth(root),
        json={"code": f"quota-{suffix}", "name": "配额客户"},
    ).json()["data"]

    from app.services.organization_settings import update_settings

    update_settings(db, uuid.UUID(org["id"]), {"quotas": {"projects": 0}})

    blocked = client.post(
        "/api/v1/projects", headers=_auth(root),
        json={"code": f"quota-new-{suffix}", "name": "超配额项目", "organization_id": org["id"]},
    )
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "organization_project_quota_exceeded"

"""客户名册：名册不等于项目访问权，同步只加 viewer。"""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_roster_does_not_grant_access_until_sync(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"orgm-{suffix}")
    admin = user_factory(f"orgm-admin-{suffix}")
    outsider = user_factory(f"orgm-out-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    add = client.post(
        f"/api/v1/projects/{project.id}/organization-members",
        headers=_auth(admin),
        json={"user_id": str(outsider.id), "role": "member"},
    )
    assert add.status_code == 200, add.text
    assert add.json()["data"]["created"] == 1

    roster = client.get(
        f"/api/v1/projects/{project.id}/organization-members", headers=_auth(admin)
    ).json()["data"]
    row = next(item for item in roster if item["user_id"] == str(outsider.id))
    assert row["in_project"] is False

    # 名册成员尚未进项目：不能读项目数据
    denied = client.get(f"/api/v1/projects/{project.id}/stats/industry", headers=_auth(outsider))
    assert denied.status_code in (403, 404)

    first = client.post(
        f"/api/v1/projects/{project.id}/organization-members/sync", headers=_auth(admin)
    ).json()["data"]
    assert first["added"] >= 1
    assert first["role_code"] == "viewer"

    allowed = client.get(f"/api/v1/projects/{project.id}/stats/industry", headers=_auth(outsider))
    assert allowed.status_code == 200, allowed.text

    second = client.post(
        f"/api/v1/projects/{project.id}/organization-members/sync", headers=_auth(admin)
    ).json()["data"]
    assert second["added"] == 0


def test_member_management_requires_permission(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"orgm-perm-{suffix}")
    admin = user_factory(f"orgm-perm-admin-{suffix}")
    viewer = user_factory(f"orgm-viewer-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, viewer, RoleCode.VIEWER)

    resp = client.post(
        f"/api/v1/projects/{project.id}/organization-members",
        headers=_auth(viewer),
        json={"user_id": str(admin.id)},
    )
    assert resp.status_code == 403, resp.text

"""项目资料确认与优先级：只允许当前项目的项目管理员执行。"""

from __future__ import annotations

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_project_admin_confirms_priority_and_audit(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"confirm-{suffix}")
    admin = user_factory(f"confirm-admin-{suffix}")
    viewer = user_factory(f"confirm-viewer-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, viewer, RoleCode.VIEWER)

    response = client.post(
        f"/api/v1/projects/{project.id}/confirm",
        json={"priority": 2, "note": "资料已收齐，优先排期"},
        headers=_auth(admin),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["priority"] == 2
    assert data["business_confirmed_at"]
    assert data["business_confirmed_by"] == str(admin.id)

    # 重新确认是幂等更新，不新增第二条项目记录。
    again = client.post(
        f"/api/v1/projects/{project.id}/confirm",
        json={"priority": 1},
        headers=_auth(admin),
    )
    assert again.status_code == 200, again.text
    assert again.json()["data"]["priority"] == 1

    audit = client.get(
        f"/api/v1/projects/{project.id}/audit-logs", headers=_auth(admin)
    )
    assert audit.status_code == 200, audit.text
    actions = [row["action"] for row in audit.json()["data"]]
    assert "project.business_confirm" in actions

    forbidden = client.post(
        f"/api/v1/projects/{project.id}/confirm",
        json={"priority": 1},
        headers=_auth(viewer),
    )
    assert forbidden.status_code == 403, forbidden.text

    invalid = client.post(
        f"/api/v1/projects/{project.id}/confirm",
        json={"priority": 6},
        headers=_auth(admin),
    )
    assert invalid.status_code == 422, invalid.text

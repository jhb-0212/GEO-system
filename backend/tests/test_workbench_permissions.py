"""六角色工作台权限矩阵：路由门禁与前端菜单使用同一套能力码。"""

from __future__ import annotations

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_workbench_role_endpoint_matrix(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"rbac-{suffix}")
    users = {
        "sys_admin": user_factory(f"rbac-sys-{suffix}", is_system_admin=True),
        "project_admin": user_factory(f"rbac-admin-{suffix}"),
        "editor": user_factory(f"rbac-editor-{suffix}"),
        "reviewer": user_factory(f"rbac-reviewer-{suffix}"),
        "viewer": user_factory(f"rbac-viewer-{suffix}"),
        "lead_ops": user_factory(f"rbac-lead-{suffix}"),
    }
    for role in ("project_admin", "editor", "reviewer", "viewer", "lead_ops"):
        member_factory(project, users[role], RoleCode(role))

    cases = [
        ("engines", "/api/v1/engines", {
            "sys_admin": 200, "project_admin": 200, "editor": 200,
            "reviewer": 403, "viewer": 403, "lead_ops": 403,
        }),
        ("diagnostics", f"/api/v1/projects/{project.id}/monitoring/diagnostics", {
            "sys_admin": 403, "project_admin": 200, "editor": 200,
            "reviewer": 403, "viewer": 403, "lead_ops": 403,
        }),
        ("leads", f"/api/v1/projects/{project.id}/leads", {
            "sys_admin": 403, "project_admin": 200, "editor": 403,
            "reviewer": 403, "viewer": 200, "lead_ops": 200,
        }),
        ("members", f"/api/v1/projects/{project.id}/members", {
            "sys_admin": 403, "project_admin": 200, "editor": 403,
            "reviewer": 403, "viewer": 403, "lead_ops": 403,
        }),
        ("audit", f"/api/v1/projects/{project.id}/audit-logs", {
            "sys_admin": 403, "project_admin": 200, "editor": 403,
            "reviewer": 200, "viewer": 403, "lead_ops": 403,
        }),
    ]

    for name, path, expected in cases:
        for role, status in expected.items():
            response = client.get(path, headers=_auth(users[role]))
            assert response.status_code == status, (
                f"{name} / {role}: expected {status}, got {response.status_code}: {response.text}"
            )


def test_viewer_lead_contact_is_masked_everywhere(
    client, db, project_factory, user_factory, member_factory
):
    """只读能读线索，但列表和导出都不能拿到完整手机号 / 微信。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mask-{suffix}")
    viewer = user_factory(f"mask-viewer-{suffix}")
    project_admin = user_factory(f"mask-admin-{suffix}")
    lead_ops = user_factory(f"mask-lead-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    member_factory(project, project_admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, lead_ops, RoleCode.LEAD_OPS)

    created = client.post(
        f"/api/v1/projects/{project.id}/leads",
        json={
            "contact_name": "张三",
            "contact_phone": "13800000002",
            "contact_wechat": "wxid_zhangsan",
            "lead_source": "验收",
            "reported_ai_product": "豆包",
            "is_valid": True,
        },
        headers=_auth(lead_ops),
    )
    assert created.status_code == 201, created.text

    viewer_list = client.get(
        f"/api/v1/projects/{project.id}/leads", headers=_auth(viewer)
    )
    assert viewer_list.status_code == 200, viewer_list.text
    viewer_row = viewer_list.json()["data"][0]
    assert viewer_row["contact_phone"] == "138****0002"
    assert viewer_row["contact_wechat"] == "wx****an"
    assert viewer_row["reported_ai_product"] == "豆包"
    assert viewer_row["is_valid"] is True

    updated = client.patch(
        f"/api/v1/projects/{project.id}/leads/{viewer_row['id']}",
        json={"reported_ai_product": "DeepSeek", "is_valid": False},
        headers=_auth(lead_ops),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["reported_ai_product"] == "DeepSeek"
    assert updated.json()["data"]["is_valid"] is False

    null_valid = client.patch(
        f"/api/v1/projects/{project.id}/leads/{viewer_row['id']}",
        json={"is_valid": None},
        headers=_auth(lead_ops),
    )
    assert null_valid.status_code == 422, null_valid.text

    null_status = client.patch(
        f"/api/v1/projects/{project.id}/leads/{viewer_row['id']}",
        json={"enrollment_status": None},
        headers=_auth(lead_ops),
    )
    assert null_status.status_code == 422, null_status.text

    admin_list = client.get(
        f"/api/v1/projects/{project.id}/leads", headers=_auth(project_admin)
    )
    assert admin_list.status_code == 200, admin_list.text
    admin_row = admin_list.json()["data"][0]
    assert admin_row["contact_phone"] == "13800000002"
    assert admin_row["contact_wechat"] == "wxid_zhangsan"

    viewer_export = client.get(
        f"/api/v1/projects/{project.id}/leads/export", headers=_auth(viewer)
    )
    assert viewer_export.status_code == 200, viewer_export.text
    assert "13800000002" not in viewer_export.text
    assert "138****0002" in viewer_export.text
    assert "wxid_zhangsan" not in viewer_export.text
    assert "wx****an" in viewer_export.text

    admin_export = client.get(
        f"/api/v1/projects/{project.id}/leads/export", headers=_auth(project_admin)
    )
    assert admin_export.status_code == 200, admin_export.text
    assert "13800000002" in admin_export.text


"""基础信息：个人资料字段 + 资质证书 CRUD 与到期口径。"""

import uuid
from datetime import date, timedelta

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_profile_patch_updates_display_fields(client, user_factory):
    user = user_factory(f"profile-{uuid.uuid4().hex[:6]}")
    patched = client.patch(
        "/api/v1/auth/me",
        json={"job_title": " 品牌运营 ", "phone": "020-1234", "wechat": "geo_brand"},
        headers=_auth(user),
    )
    assert patched.status_code == 200, patched.text
    data = patched.json()["data"]
    assert data["job_title"] == "品牌运营"
    assert data["phone"] == "020-1234"
    assert data["wechat"] == "geo_brand"

    # 空对象不写库
    empty = client.patch("/api/v1/auth/me", json={}, headers=_auth(user))
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "empty_update"

    # 姓名不允许清空
    blank = client.patch("/api/v1/auth/me", json={"display_name": "   "}, headers=_auth(user))
    assert blank.status_code == 400

    me = client.get("/api/v1/auth/me", headers=_auth(user))
    assert me.json()["data"]["job_title"] == "品牌运营"


def test_certification_crud_and_expiry_status(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cert-{suffix}")
    editor = user_factory(f"cert-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}/certifications"

    today = date.today()
    created = client.post(
        base,
        json={
            "name": "办学许可证",
            "category": "资质",
            "issuer": "教育局",
            "cert_no": "教民 123",
            "issued_on": str(today - timedelta(days=365)),
            "expires_on": str(today + timedelta(days=30)),
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    # 30 天内到期 → expiring，天数由接口算好
    assert row["status"] == "expiring"
    assert row["days_left"] == 30

    expired = client.post(
        base,
        json={"name": "过期资质", "expires_on": str(today - timedelta(days=2))},
        headers=_auth(editor),
    )
    assert expired.json()["data"]["status"] == "expired"
    assert expired.json()["data"]["days_left"] == -2

    no_expiry = client.post(base, json={"name": "长期有效"}, headers=_auth(editor))
    assert no_expiry.json()["data"]["status"] is None

    # 列表按到期日升序，无到期日的排最后
    listed = client.get(base, headers=_auth(editor))
    names = [item["name"] for item in listed.json()["data"]]
    assert names == ["过期资质", "办学许可证", "长期有效"]

    # 日期倒挂被拒
    bad = client.post(
        base,
        json={
            "name": "倒挂",
            "issued_on": str(today),
            "expires_on": str(today - timedelta(days=1)),
        },
        headers=_auth(editor),
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "certification_date_invalid"

    patched = client.patch(f"{base}/{row['id']}", json={"is_active": False}, headers=_auth(editor))
    assert patched.status_code == 200
    active_only = client.get(base, headers=_auth(editor))
    assert all(item["id"] != row["id"] for item in active_only.json()["data"])
    with_inactive = client.get(base, params={"include_inactive": True}, headers=_auth(editor))
    assert any(item["id"] == row["id"] for item in with_inactive.json()["data"])

    removed = client.delete(f"{base}/{row['id']}", headers=_auth(editor))
    assert removed.status_code == 200
    assert removed.json()["data"]["deleted"] is True

    # 只读角色不能写
    viewer = user_factory(f"cert-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    denied = client.post(base, json={"name": "越权新增"}, headers=_auth(viewer))
    assert denied.status_code == 403
    assert client.get(base, headers=_auth(viewer)).status_code == 200

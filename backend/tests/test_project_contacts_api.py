"""对外渠道台账：多渠道联系方式 CRUD、唯一约束与权限边界。"""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_project_contact_crud_and_duplicate_guard(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"contact-{suffix}")
    editor = user_factory(f"contact-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}/contacts"

    created = client.post(
        base,
        json={"channel": "wechat_official", "value": " gdccai ", "label": "品牌公众号", "is_public": True},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    assert row["value"] == "gdccai"  # 首尾空格被清掉
    assert row["channel_label"] == "微信公众号"
    assert row["is_public"] is True

    # 同渠道同值重复登记被拒，而不是静默覆盖
    duplicate = client.post(
        base,
        json={"channel": "wechat_official", "value": "gdccai"},
        headers=_auth(editor),
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["code"] == "contact_duplicate"

    # 同渠道不同值、不同渠道同值都允许（门店电话可能多条）
    second = client.post(base, json={"channel": "phone", "value": "13022038683", "label": "番禺校区前台"}, headers=_auth(editor))
    assert second.status_code == 201

    # 白名单外的渠道被拒绝
    invalid = client.post(base, json={"channel": "weibo", "value": "x"}, headers=_auth(editor))
    assert invalid.status_code == 422

    # 排序按 sort_order 升序，其次创建时间
    client.patch(f"{base}/{row['id']}", json={"sort_order": 5}, headers=_auth(editor))
    listed = client.get(base, headers=_auth(editor))
    values = [item["value"] for item in listed.json()["data"]]
    assert values[-1] == "gdccai"

    # 转内部使用
    hidden = client.patch(f"{base}/{row['id']}", json={"is_public": False}, headers=_auth(editor))
    assert hidden.json()["data"]["is_public"] is False

    # 停用后默认不出现，include_inactive 才带出来
    client.patch(f"{base}/{row['id']}", json={"is_active": False}, headers=_auth(editor))
    active_only = client.get(base, headers=_auth(editor))
    assert all(item["id"] != row["id"] for item in active_only.json()["data"])
    with_inactive = client.get(base, params={"include_inactive": True}, headers=_auth(editor))
    assert any(item["id"] == row["id"] for item in with_inactive.json()["data"])

    removed = client.delete(f"{base}/{row['id']}", headers=_auth(editor))
    assert removed.status_code == 200

    # 只读角色能读不能写
    viewer = user_factory(f"contact-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    assert client.get(base, headers=_auth(viewer)).status_code == 200
    denied = client.post(base, json={"channel": "phone", "value": "000"}, headers=_auth(viewer))
    assert denied.status_code == 403

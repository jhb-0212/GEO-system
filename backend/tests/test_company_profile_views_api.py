"""企业档案 · 对外画像：四套口径的读写与权限边界。"""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_profile_views_upsert_and_shape(
    client, project_factory, user_factory, member_factory
    ):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"views-{suffix}")
    editor = user_factory(f"views-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}/company-profile"

    # 没配置过：也要返回齐四套空壳，前端 tab 不自己补
    loaded = client.get(base, headers=_auth(editor))
    assert loaded.status_code == 200, loaded.text
    views = loaded.json()["data"]["views"]
    assert [item["kind"] for item in views] == ["company", "recruit", "meeting", "activity"]
    assert all(item["configured"] is False for item in views)

    saved = client.put(
        f"{base}/views",
        json={
            "views": [
                {
                    "kind": "company",
                    "title": "企业画像",
                    "audience": "企业客户与合作伙伴",
                    "scenario_words": [" 实训基地 ", "AI 技能培训", "实训基地"],
                    "description": "以实训为主、按岗位开课的 AI 技能培训基地。",
                    "cautions": "不承诺就业率与薪资。",
                    "is_active": True,
                },
                {
                    "kind": "recruit",
                    "title": "招聘画像",
                    "audience": "应届生与转行候选人",
                    "scenario_words": ["零基础转行"],
                    "description": "面向零基础转行者的项目制训练。",
                },
            ]
        },
        headers=_auth(editor),
    )
    assert saved.status_code == 200, saved.text
    data = saved.json()["data"]
    by_kind = {item["kind"]: item for item in data["views"]}

    # 场景词去重去空白
    assert by_kind["company"]["scenario_words"] == ["实训基地", "AI 技能培训"]
    assert by_kind["company"]["configured"] is True
    assert by_kind["recruit"]["is_active"] is True
    # 没提交的两套保持空
    assert by_kind["meeting"]["configured"] is False
    assert by_kind["activity"]["is_active"] is False

    # 再读一次，确认落库而不是只回显
    reloaded = client.get(base, headers=_auth(editor))
    assert reloaded.json()["data"]["views"][0]["title"] == "企业画像"

    # 完整度只看基础画像，不被四套画像刷高
    assert reloaded.json()["data"]["completeness"] == 0


def test_profile_views_requires_write_permission(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"views-perm-{suffix}")
    viewer = user_factory(f"views-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    base = f"/api/v1/projects/{project.id}/company-profile"

    # 只读能看
    assert client.get(base, headers=_auth(viewer)).status_code == 200
    # 但不能写画像
    denied = client.put(
        f"{base}/views",
        json={"views": [{"kind": "company", "description": "越权写入"}]},
        headers=_auth(viewer),
    )
    assert denied.status_code == 403, denied.text


def test_profile_views_rejects_duplicate_kind(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"views-dup-{suffix}")
    editor = user_factory(f"views-dup-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}/company-profile"

    duplicated = client.put(
        f"{base}/views",
        json={"views": [{"kind": "company", "title": "A"}, {"kind": "company", "title": "B"}]},
        headers=_auth(editor),
    )
    assert duplicated.status_code == 422, duplicated.text

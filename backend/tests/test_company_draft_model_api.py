"""起草模型配置回归：界面填 Key 生效、Key 不回显、优先级、权限、连通性测试。

覆盖口径：
- 没配过的项目照旧回落环境变量，界面显示 source=env；
- 项目里配了 Key 就立刻生效（`mode=ai` 用的是项目里那把，不是环境变量那把）；
- 接口只回显指纹与是否有 Key，绝不回显明文；
- `api_key` 留空不改已存 Key，`clear_key=true` 才清空；
- 只读角色不能读也不能写。
"""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode
from app.services import company_draft
from app.services.company_draft import ChatTarget


def _auth(user) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"
    }


def _seed_project(db, project_factory, user_factory, member_factory, prefix: str, role=RoleCode.EDITOR):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"{prefix}-{suffix}")
    member = user_factory(f"{prefix}-{role.value}-{suffix}")
    member_factory(project, member, role)
    return project, member


def test_model_setting_falls_back_to_env(client, db, project_factory, user_factory, member_factory, monkeypatch):
    project, editor = _seed_project(db, project_factory, user_factory, member_factory, "dm-env")
    monkeypatch.setattr(company_draft, "read_credential_env", lambda _ref: "sk-env-1234567890")

    resp = client.get(f"/api/v1/projects/{project.id}/company-profile/draft-model", headers=_auth(editor))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["source"] == "env"
    assert data["configured"] is True
    assert data["has_secret"] is False
    # 指纹只留前 6 位 + 后 4 位
    assert data["env_key_hint"] == "sk-env…7890"


def test_model_setting_project_key_wins_and_is_not_echoed(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project, editor = _seed_project(db, project_factory, user_factory, member_factory, "dm-project")
    monkeypatch.setattr(company_draft, "read_credential_env", lambda _ref: "sk-env-1234567890")

    secret = "sk-7ae6420b10094865ab5881685de46785"
    resp = client.put(
        f"/api/v1/projects/{project.id}/company-profile/draft-model",
        headers=_auth(editor),
        json={"base_url": "https://api.deepseek.com/", "model": "deepseek-chat", "api_key": secret},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["source"] == "project"
    assert data["has_secret"] is True
    assert data["base_url"] == "https://api.deepseek.com"
    assert secret not in resp.text

    # 落库后重读一致（不是只活在内存里）
    again = client.get(
        f"/api/v1/projects/{project.id}/company-profile/draft-model", headers=_auth(editor)
    ).json()["data"]
    assert again["source"] == "project"
    assert again["has_secret"] is True

    # 留空 Key 只改型号，已存 Key 不能丢
    resp = client.put(
        f"/api/v1/projects/{project.id}/company-profile/draft-model",
        headers=_auth(editor),
        json={"model": "deepseek-chat-v2"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["has_secret"] is True
    assert resp.json()["data"]["model"] == "deepseek-chat-v2"

    # clear_key 才清空
    resp = client.put(
        f"/api/v1/projects/{project.id}/company-profile/draft-model",
        headers=_auth(editor),
        json={"clear_key": True},
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()["data"]
    assert after["has_secret"] is False
    assert after["source"] == "env"


def test_draft_uses_project_key_before_env(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project, editor = _seed_project(db, project_factory, user_factory, member_factory, "dm-priority")
    monkeypatch.setattr(company_draft, "read_credential_env", lambda _ref: "sk-env-1234567890")

    client.put(
        f"/api/v1/projects/{project.id}/company-profile/draft-model",
        headers=_auth(editor),
        json={"api_key": "sk-project-0987654321"},
    )

    captured: dict[str, ChatTarget] = {}

    def _fake_draft(target, evidence):
        captured["target"] = target
        return {"slogan": "授实用技术，铺成长坦途"}

    monkeypatch.setattr(company_draft, "draft_with_model", _fake_draft)

    resp = client.post(f"/api/v1/projects/{project.id}/company-profile/draft", headers=_auth(editor))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["mode"] == "ai"
    assert captured["target"].secret == "sk-project-0987654321"
    assert captured["target"].model == "deepseek-chat"


def test_model_setting_test_endpoint_reports_result(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project, editor = _seed_project(db, project_factory, user_factory, member_factory, "dm-test")
    monkeypatch.setattr(company_draft, "read_credential_env", lambda _ref: "")
    client.put(
        f"/api/v1/projects/{project.id}/company-profile/draft-model",
        headers=_auth(editor),
        json={"api_key": "sk-project-0987654321"},
    )

    # api 层是按名字导入的，要打在 api.company 上才拦得住真实请求
    from app.api import company as company_api
    monkeypatch.setattr(company_api, "test_chat_target", lambda target: (True, "连接正常，模型可用：OK"))
    resp = client.post(
        f"/api/v1/projects/{project.id}/company-profile/draft-model/test", headers=_auth(editor)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["ok"] is True
    assert data["model"] == "deepseek-chat"
    assert "连接正常" in data["message"]


def test_model_setting_requires_brand_manage(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project, viewer = _seed_project(db, project_factory, user_factory, member_factory, "dm-viewer", RoleCode.VIEWER)
    monkeypatch.setattr(company_draft, "read_credential_env", lambda _ref: "")

    assert (
        client.get(
            f"/api/v1/projects/{project.id}/company-profile/draft-model", headers=_auth(viewer)
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/v1/projects/{project.id}/company-profile/draft-model",
            headers=_auth(viewer),
            json={"api_key": "sk-should-not-save"},
        ).status_code
        == 403
    )

"""第二轮审查 P1 回归：项目自助、管理员守卫、内容当前版本、入口地址策略。"""

from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import ContentItem, ContentVersion, Role
from app.models.enums import ContentStatus, EngineProtocol, RoleCode
from app.services.engine_connectors import test_entry_connection as probe_entry_connection
from app.services.engine_url_policy import validate_engine_url


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_create_project_grants_owner_membership(client, db, user_factory):
    suffix = uuid.uuid4().hex[:6]
    sys_admin = user_factory(f"create-{suffix}", is_system_admin=True)
    response = client.post(
        "/api/v1/projects",
        json={"code": f"new-{suffix}", "name": "新项目", "timezone": "Asia/Shanghai"},
        headers=_auth(sys_admin),
    )
    assert response.status_code == 201, response.text
    project_id = response.json()["data"]["id"]
    assert response.json()["data"]["owner_name"] == sys_admin.username

    members = client.get(f"/api/v1/projects/{project_id}/members", headers=_auth(sys_admin))
    assert members.status_code == 200, members.text
    rows = members.json()["data"]
    assert len(rows) == 1
    assert rows[0]["user_id"] == str(sys_admin.id)
    assert rows[0]["role_code"] == RoleCode.PROJECT_ADMIN.value


def test_add_member_cannot_demote_existing_project_admin(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"guard-{suffix}")
    actor = user_factory(f"guard-a-{suffix}")
    target = user_factory(f"guard-b-{suffix}")
    member_factory(project, actor, RoleCode.PROJECT_ADMIN)
    target_member = member_factory(project, target, RoleCode.PROJECT_ADMIN)

    response = client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": str(target.id), "role_code": "editor"},
        headers=_auth(actor),
    )
    assert response.status_code == 403, response.text
    db.refresh(target_member)
    role = db.scalar(select(Role).where(Role.id == target_member.role_id))
    assert role.code == RoleCode.PROJECT_ADMIN.value


def test_new_version_and_review_are_bound_to_current_version(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"curr-{suffix}")
    editor = user_factory(f"curr-editor-{suffix}")
    reviewer = user_factory(f"curr-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    base = f"/api/v1/projects/{project.id}"

    item = client.post(
        f"{base}/contents", json={"title": "当前版本测试", "kind": "master"}, headers=_auth(editor)
    ).json()["data"]
    item_id = item["item_id"]
    v1 = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": "第一版正文", "change_note": "v1"},
        headers=_auth(editor),
    ).json()["data"]["version_id"]
    assert (
        client.post(f"{base}/content-versions/{v1}/submit", headers=_auth(editor)).status_code
        == 200
    )

    # 当前版本 pending_review 时，不能再建新版本制造第二份待审稿。
    blocked = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": "抢跑第二版", "change_note": "v2"},
        headers=_auth(editor),
    )
    assert blocked.status_code == 409, blocked.text

    # 存量分叉数据：把 item.current_version_id 指到另一版本后，旧版不能再审批。
    row = db.get(ContentItem, uuid.UUID(item_id))
    v2 = ContentVersion(
        project_id=project.id,
        item_id=row.id,
        version_no=2,
        body="手工构造的第二版",
        content_hash=hashlib.sha256(b"manual-v2").hexdigest(),
        status=ContentStatus.DRAFT,
        created_by=editor.id,
    )
    db.add(v2)
    db.flush()
    row.current_version_id = v2.id
    db.flush()

    stale_review = client.post(
        f"{base}/content-versions/{v1}/review",
        json={"decision": "approved"},
        headers=_auth(reviewer),
    )
    assert stale_review.status_code == 409, stale_review.text


def test_engine_url_policy_rejects_non_official_endpoint_and_internal_ip(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-example")
    with pytest.raises(ValueError, match="官方 host"):
        validate_engine_url(
            "https://evil.example.com/v2/ai_search/web_search",
            EngineProtocol.WENXIN_SEARCH,
        )
    with pytest.raises(ValueError, match="内网"):
        validate_engine_url("http://10.0.0.8/v1", EngineProtocol.OPENAI_COMPATIBLE)

    entry = SimpleNamespace(
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="http://10.0.0.8/v1",
        model_name="deepseek-chat",
        credential_ref="DEEPSEEK_API_KEY",
    )
    result = probe_entry_connection(entry)
    assert result["success"] is False
    assert result["error_code"] == "entry_url_invalid"
    assert "未发起真实请求" not in result["message"]


def test_engine_url_policy_custom_allows_public_https_but_blocks_internal():
    """custom 用于登记待接入平台：允许公网 https 地址，仍拒绝内网与 IP 字面量。"""
    assert (
        validate_engine_url("https://example.com/v1", EngineProtocol.CUSTOM)
        == "https://example.com/v1"
    )
    with pytest.raises(ValueError, match="内网"):
        validate_engine_url("https://10.0.0.8/v1", EngineProtocol.CUSTOM)

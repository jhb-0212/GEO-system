"""K4 百科词条：只能走自己的状态机，不能绕过审核发布。

钉住五条：
1. 建条目是草稿，slug 自动生成且同项目不重复；
2. 没参考资料的词条不能提交（审核无从核验）；
3. 待审/已发布词条不可直接改（要改先撤回或另起版本）；
4. 只有 `content.review` 的人能审，驳回后回到草稿可再提交；
5. 只有审核通过的词条能登记外链，非 http(s) 直接 422。
"""

import uuid

from app.core.security import create_access_token
from app.models.enums import EncyclopediaStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _setup(project_factory, user_factory, member_factory, role=RoleCode.EDITOR):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"enc-{suffix}")
    user = user_factory(f"enc-u-{suffix}")
    member_factory(project, user, role)
    return project, user


def _add_reviewer(project, user_factory, member_factory):
    reviewer = user_factory(f"enc-r-{uuid.uuid4().hex[:6]}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    return reviewer


def _create(client, project, user, **overrides):
    payload = {
        "title": "广东省AI数字人才就业实训基地",
        "platform": "baidu_baike",
        "summary": "省级 AI 数字人才实训基地",
        "body": "基地面向应届生提供 AIGC 实训，课程按项目制推进。",
        "references": [{"title": "官网简介", "url": "https://gdccai.com/about", "note": "一手来源"}],
    }
    payload.update(overrides)
    return client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries", json=payload, headers=_auth(user)
    )


def test_create_entry_is_draft_with_unique_slug(
    client, project_factory, user_factory, member_factory
):
    project, user = _setup(project_factory, user_factory, member_factory)
    first = _create(client, project, user)
    assert first.status_code == 201, first.text
    data = first.json()["data"]
    assert data["status"] == "draft"
    assert data["platform_label"] == "百度百科"
    assert data["slug"]

    second = _create(client, project, user)  # 同名词条不能撞 slug
    assert second.status_code == 201
    assert second.json()["data"]["slug"] != data["slug"]


def test_submit_requires_references(client, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    entry = _create(client, project, user, references=[]).json()["data"]
    resp = client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry['entry_id']}/submit",
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "encyclopedia_references_required"


def test_pending_entry_is_locked(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    entry = _create(client, project, user).json()["data"]
    entry_id = entry["entry_id"]
    resp = client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}/submit",
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "pending_review"

    resp = client.patch(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}",
        json={"body": "偷偷改正文"},
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "encyclopedia_entry_locked"


def test_review_requires_permission_and_reject_reopens(
    client, project_factory, user_factory, member_factory
):
    project, editor = _setup(project_factory, user_factory, member_factory)
    reviewer = _add_reviewer(project, user_factory, member_factory)
    entry = _create(client, project, editor).json()["data"]
    entry_id = entry["entry_id"]
    client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}/submit",
        headers=_auth(editor),
    )
    # 提交人没有 content.review，审不了
    resp = client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}/review",
        json={"approve": True},
        headers=_auth(editor),
    )
    assert resp.status_code == 403

    resp = client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}/review",
        json={"approve": False, "note": "参考资料缺第三方来源"},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "rejected"

    # 驳回后可以改，改完回草稿
    resp = client.patch(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}",
        json={"references": [{"title": "媒体报道", "url": "https://example.com/a", "note": "第三方"}]},
        headers=_auth(editor),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "draft"


def test_publication_only_after_approval(
    client, db, project_factory, user_factory, member_factory
):
    project, editor = _setup(project_factory, user_factory, member_factory)
    reviewer = _add_reviewer(project, user_factory, member_factory)
    entry = _create(client, project, editor).json()["data"]
    entry_id = entry["entry_id"]

    resp = client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}/publication",
        json={"published_url": "https://baike.baidu.com/item/x"},
        headers=_auth(editor),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "encyclopedia_status_invalid"

    client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}/submit",
        headers=_auth(editor),
    )
    client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}/review",
        json={"approve": True},
        headers=_auth(reviewer),
    )
    resp = client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}/publication",
        json={"published_url": "https://baike.baidu.com/item/x"},
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "published"
    assert data["published_url"].startswith("https://")

    resp = client.post(
        f"/api/v1/projects/{project.id}/encyclopedia-entries/{entry_id}/publication",
        json={"published_url": "baike.baidu.com/item/x"},
        headers=_auth(editor),
    )
    assert resp.status_code == 422

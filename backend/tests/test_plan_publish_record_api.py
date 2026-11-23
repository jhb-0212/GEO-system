"""B7 新媒体发布记录：计划上的「是否已发布 / 发布链接 / 人工备注」。

钉住三条：
1. 说已发布不带链接 → 422 publish_url_required；
2. 挂链接但没标已发布 → 422 publish_url_without_published；
3. 链接必须 http(s)；撤回发布时链接与 published_at 一并清空。
"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import ContentPlan
from app.models.enums import ContentPlanStatus, PlanType, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _project_and_editor(project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"plan-b7-{suffix}")
    editor = user_factory(f"plan-b7-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    return project, editor


def _create_plan(client, project, editor, **overrides):
    payload = {
        "title": f"计划-{uuid.uuid4().hex[:6]}",
        "plan_type": PlanType.VIDEO.value,
        "status": ContentPlanStatus.PUBLISHED.value,
    }
    payload.update(overrides)
    return client.post(
        f"/api/v1/projects/{project.id}/plans", json=payload, headers=_auth(editor)
    )


def _only_plan(client, project, editor, plan_id: str) -> dict:
    listing = client.get(
        f"/api/v1/projects/{project.id}/plans?page_size=100", headers=_auth(editor)
    )
    assert listing.status_code == 200, listing.text
    for row in listing.json()["data"]:
        if row["id"] == plan_id:
            return row
    raise AssertionError("计划未出现在列表里")


def test_published_requires_publish_url(client, db, project_factory, user_factory, member_factory):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    resp = _create_plan(client, project, editor, is_published=True)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "publish_url_required"


def test_url_without_published_flag_is_rejected(
    client, db, project_factory, user_factory, member_factory
):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    resp = _create_plan(client, project, editor, publish_url="https://www.douyin.com/video/123")
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "publish_url_without_published"


def test_publish_url_must_be_http(client, db, project_factory, user_factory, member_factory):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    resp = _create_plan(
        client, project, editor, is_published=True, publish_url="www.douyin.com/video/123"
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "publish_url_invalid"


def test_publish_record_roundtrip_and_revoke(
    client, db, project_factory, user_factory, member_factory
):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    resp = _create_plan(
        client, project, editor,
        is_published=True,
        publish_url="https://www.douyin.com/video/7300000000",
        play_note="首日播放 1.2w，评论 30 条（人工记录）",
    )
    assert resp.status_code == 201, resp.text
    plan_id = resp.json()["data"]["id"]

    row = _only_plan(client, project, editor, plan_id)
    assert row["is_published"] is True
    assert row["publish_url"] == "https://www.douyin.com/video/7300000000"
    assert row["published_at"] is not None
    assert "1.2w" in row["play_note"]

    # 撤回发布：链接与发布时间一并清空；备注保留（备注是运营的历史说明，不随发布状态消失）
    revoked = client.patch(
        f"/api/v1/projects/{project.id}/plans/{plan_id}",
        json={"is_published": False},
        headers=_auth(editor),
    )
    assert revoked.status_code == 200, revoked.text
    body = revoked.json()["data"]
    assert body["is_published"] is False
    assert body["publish_url"] is None
    assert body["published_at"] is None

    db_row = db.scalar(select(ContentPlan).where(ContentPlan.id == uuid.UUID(plan_id)))
    assert db_row is not None and db_row.publish_url is None


def test_publish_url_patch_alone_rejected_when_not_published(
    client, db, project_factory, user_factory, member_factory
):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    created = _create_plan(client, project, editor)
    assert created.status_code == 201, created.text
    plan_id = created.json()["data"]["id"]

    resp = client.patch(
        f"/api/v1/projects/{project.id}/plans/{plan_id}",
        json={"publish_url": "https://www.xiaohongshu.com/explore/abc"},
        headers=_auth(editor),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "publish_url_without_published"


def test_published_filter_on_list(client, db, project_factory, user_factory, member_factory):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    created = _create_plan(
        client, project, editor, is_published=True, publish_url="https://www.bilibili.com/video/BV1"
    )
    assert created.status_code == 201, created.text

    published = client.get(
        f"/api/v1/projects/{project.id}/plans?is_published=true", headers=_auth(editor)
    )
    assert published.status_code == 200, published.text
    assert published.json()["meta"]["total"] == 1

    unpublished = client.get(
        f"/api/v1/projects/{project.id}/plans?is_published=false", headers=_auth(editor)
    )
    assert unpublished.status_code == 200, unpublished.text
    assert unpublished.json()["meta"]["total"] == 0

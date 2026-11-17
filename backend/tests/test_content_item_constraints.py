"""内容条目关系约束与 item/version 状态同步回归。"""

import uuid

from app.core.security import create_access_token
from app.models import Channel, ContentItem
from app.models.enums import (
    ChannelCategory,
    ChannelStatus,
    ContentStatus,
    RoleCode,
)


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _channel(db, project, suffix):
    channel = Channel(
        project_id=project.id,
        code=f"content-contract-{suffix}",
        name="内容约束测试渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.OBSERVED,
        is_active=True,
    )
    db.add(channel)
    db.flush()
    return channel


def test_channel_item_requires_parent_and_channel(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"content-link-{suffix}")
    editor = user_factory(f"content-link-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}"

    missing = client.post(
        f"{base}/contents",
        json={"title": "缺关系渠道稿", "kind": "channel"},
        headers=_auth(editor),
    )
    assert missing.status_code == 422

    channel = _channel(db, project, suffix)
    master_with_channel = client.post(
        f"{base}/contents",
        json={
            "title": "错误挂渠道的母稿",
            "kind": "master",
            "channel_id": str(channel.id),
        },
        headers=_auth(editor),
    )
    assert master_with_channel.status_code == 422

    master = client.post(
        f"{base}/contents",
        json={"title": "母稿", "kind": "master"},
        headers=_auth(editor),
    )
    assert master.status_code == 201
    valid = client.post(
        f"{base}/contents",
        json={
            "title": "渠道稿",
            "kind": "channel",
            "parent_id": master.json()["data"]["item_id"],
            "channel_id": str(channel.id),
        },
        headers=_auth(editor),
    )
    assert valid.status_code == 201


def test_channel_parent_must_be_master(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"content-parent-{suffix}")
    editor = user_factory(f"content-parent-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}"
    channel = _channel(db, project, suffix)

    master = client.post(
        f"{base}/contents",
        json={"title": "母稿", "kind": "master"},
        headers=_auth(editor),
    )
    assert master.status_code == 201
    master_id = master.json()["data"]["item_id"]

    first_channel = client.post(
        f"{base}/contents",
        json={
            "title": "第一层渠道稿",
            "kind": "channel",
            "parent_id": master_id,
            "channel_id": str(channel.id),
        },
        headers=_auth(editor),
    )
    assert first_channel.status_code == 201
    first_channel_id = first_channel.json()["data"]["item_id"]

    nested = client.post(
        f"{base}/contents",
        json={
            "title": "错误挂渠道稿的渠道稿",
            "kind": "channel",
            "parent_id": first_channel_id,
            "channel_id": str(channel.id),
        },
        headers=_auth(editor),
    )
    assert nested.status_code == 409


def test_item_status_tracks_version_status(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"content-status-{suffix}")
    editor = user_factory(f"content-status-editor-{suffix}")
    reviewer = user_factory(f"content-status-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    base = f"/api/v1/projects/{project.id}"

    item = client.post(
        f"{base}/contents",
        json={"title": "状态同步母稿", "kind": "master"},
        headers=_auth(editor),
    )
    assert item.status_code == 201
    item_id = item.json()["data"]["item_id"]

    version = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": "状态同步正文"},
        headers=_auth(editor),
    )
    assert version.status_code == 201
    version_id = version.json()["data"]["version_id"]
    assert db.get(ContentItem, uuid.UUID(item_id)).status == ContentStatus.DRAFT

    assert client.post(
        f"{base}/content-versions/{version_id}/submit",
        headers=_auth(editor),
    ).status_code == 200
    assert db.get(ContentItem, uuid.UUID(item_id)).status == ContentStatus.PENDING_REVIEW

    assert client.post(
        f"{base}/content-versions/{version_id}/review",
        json={"decision": "approved"},
        headers=_auth(reviewer),
    ).status_code == 200
    assert db.get(ContentItem, uuid.UUID(item_id)).status == ContentStatus.APPROVED

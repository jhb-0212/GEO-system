"""B7 渠道写接口回归：新增、局部更新、旧名称/旧域名保留与权限边界。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AuditLog, Channel, ChannelAlias
from app.models.enums import ChannelCategory, ChannelStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_create_channel_and_patch_preserves_old_identity(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"channel-write-{suffix}")
    editor = user_factory(f"channel-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    create_response = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": f"ch-{suffix}",
            "name": "测试渠道",
            "category": "content_platform",
            "primary_domain": "Example.COM.",
            "aliases": ["old.example.com", "old.example.com"],
            "notes": "初始备注",
        },
        headers=_auth(editor),
    )
    assert create_response.status_code == 201, create_response.text
    created = create_response.json()["data"]
    assert created["code"] == f"ch-{suffix}"
    assert created["category"] == "content_platform"
    assert created["status"] == "candidate"
    assert created["primary_domain"] == "example.com"

    channel = db.scalar(
        select(Channel).where(
            Channel.project_id == project.id,
            Channel.code == f"ch-{suffix}",
        )
    )
    assert channel is not None
    aliases = db.scalars(
        select(ChannelAlias).where(ChannelAlias.channel_id == channel.id)
    ).all()
    assert {row.domain for row in aliases} == {"old.example.com"}

    patch_response = client.patch(
        f"/api/v1/projects/{project.id}/channels/{channel.id}",
        json={
            "name": "新渠道名称",
            "category": "video",
            "status": "observed",
            "primary_domain": "new.example.com",
            "aliases": ["extra.example.com"],
        },
        headers=_auth(editor),
    )
    assert patch_response.status_code == 200, patch_response.text
    updated = patch_response.json()["data"]
    assert updated["name"] == "新渠道名称"
    assert updated["category"] == "video"
    assert updated["status"] == "observed"
    assert updated["primary_domain"] == "new.example.com"

    aliases = db.scalars(
        select(ChannelAlias)
        .where(ChannelAlias.channel_id == channel.id)
        .order_by(ChannelAlias.domain)
    ).all()
    assert {row.domain for row in aliases} == {
        "example.com",
        "extra.example.com",
        "old.example.com",
    }
    old_domain_alias = next(row for row in aliases if row.domain == "example.com")
    assert old_domain_alias.alias_name == "测试渠道"

    audits = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.target_id == channel.id,
        )
    ).all()
    assert {row.action for row in audits} == {"channel.create", "channel.update"}


def test_channel_write_permissions_and_duplicates(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"channel-perm-{suffix}")
    viewer = user_factory(f"channel-viewer-{suffix}")
    outsider = user_factory(f"channel-outsider-{suffix}")
    editor = user_factory(f"channel-editor2-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    member_factory(project, editor, RoleCode.EDITOR)

    existing = Channel(
        project_id=project.id,
        code=f"dup-{suffix}",
        name="已有渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
    )
    db.add(existing)
    db.flush()

    viewer_create = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": f"viewer-{suffix}",
            "name": "只读角色渠道",
            "category": "content_platform",
        },
        headers=_auth(viewer),
    )
    assert viewer_create.status_code == 403

    duplicate = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": existing.code,
            "name": "重复 code",
            "category": "content_platform",
        },
        headers=_auth(editor),
    )
    assert duplicate.status_code == 400

    outsider_patch = client.patch(
        f"/api/v1/projects/{project.id}/channels/{existing.id}",
        json={"name": "越权改名"},
        headers=_auth(outsider),
    )
    assert outsider_patch.status_code == 403

    bad_domain = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": f"bad-{suffix}",
            "name": "非法域名",
            "category": "content_platform",
            "primary_domain": "https://example.com/path",
        },
        headers=_auth(editor),
    )
    assert bad_domain.status_code == 422

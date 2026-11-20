"""B7 渠道写接口回归：新增、局部更新、旧名称/旧域名保留与权限边界。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AuditLog, BrandProfile, Channel, ChannelAlias, Material, PublishAccount
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    MaterialCategory,
    RoleCode,
)


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
            "owner_name": "渠道运营负责人",
            "owner_contact": "ops@example.com",
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
    assert created["owner_name"] == "渠道运营负责人"
    assert created["owner_contact"] == "ops@example.com"
    assert created["notes"] == "初始备注"
    assert created["is_active"] is True
    assert created["aliases"] == [
        {"domain": "old.example.com", "alias_name": "测试渠道"}
    ]

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
            "owner_name": "新负责人",
            "owner_contact": "new-ops@example.com",
            "notes": None,
            "is_active": False,
        },
        headers=_auth(editor),
    )
    assert patch_response.status_code == 200, patch_response.text
    updated = patch_response.json()["data"]
    assert updated["name"] == "新渠道名称"
    assert updated["category"] == "video"
    assert updated["status"] == "observed"
    assert updated["primary_domain"] == "new.example.com"
    assert updated["owner_name"] == "新负责人"
    assert updated["owner_contact"] == "new-ops@example.com"
    assert updated["notes"] is None
    assert updated["is_active"] is False
    assert updated["aliases"] == [
        {"domain": "example.com", "alias_name": "测试渠道"},
        {"domain": "extra.example.com", "alias_name": "新渠道名称"},
        {"domain": "old.example.com", "alias_name": "测试渠道"},
    ]

    detail_response = client.get(
        f"/api/v1/projects/{project.id}/channels/{channel.id}",
        headers=_auth(editor),
    )
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()["data"]
    assert detail["notes"] is None
    assert detail["owner_name"] == "新负责人"
    assert detail["owner_contact"] == "new-ops@example.com"
    assert detail["is_active"] is False
    assert detail["aliases"] == updated["aliases"]

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


def test_project_admin_can_write_channel(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"channel-admin-{suffix}")
    admin = user_factory(f"channel-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    create_response = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": f"admin-{suffix}",
            "name": "项目管理员渠道",
            "category": "content_platform",
        },
        headers=_auth(admin),
    )
    assert create_response.status_code == 201, create_response.text
    channel_id = create_response.json()["data"]["id"]

    patch_response = client.patch(
        f"/api/v1/projects/{project.id}/channels/{channel_id}",
        json={"category": "video"},
        headers=_auth(admin),
    )
    assert patch_response.status_code == 200, patch_response.text
    assert patch_response.json()["data"]["category"] == "video"


def test_primary_domain_conflicts_with_existing_primary_and_alias(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"channel-domain-{suffix}")
    editor = user_factory(f"channel-domain-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    primary = f"taken-{suffix}.example.com"
    alias = f"alias-taken-{suffix}.example.com"
    first = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": f"first-{suffix}",
            "name": "已有渠道",
            "category": "content_platform",
            "primary_domain": primary,
            "aliases": [alias],
        },
        headers=_auth(editor),
    )
    assert first.status_code == 201, first.text

    duplicate_primary = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": f"dup-primary-{suffix}",
            "name": "重复主域名",
            "category": "content_platform",
            "primary_domain": primary,
        },
        headers=_auth(editor),
    )
    assert duplicate_primary.status_code == 400, duplicate_primary.text
    assert duplicate_primary.json()["error"]["code"] == "channel_domain_conflict"

    alias_as_primary = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": f"alias-primary-{suffix}",
            "name": "别名当主域名",
            "category": "content_platform",
            "primary_domain": alias,
        },
        headers=_auth(editor),
    )
    assert alias_as_primary.status_code == 400, alias_as_primary.text
    assert alias_as_primary.json()["error"]["code"] == "channel_domain_conflict"

    second = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": f"second-{suffix}",
            "name": "待改主域名",
            "category": "content_platform",
            "primary_domain": f"second-{suffix}.example.com",
        },
        headers=_auth(editor),
    )
    assert second.status_code == 201, second.text
    patch_conflict = client.patch(
        f"/api/v1/projects/{project.id}/channels/{second.json()['data']['id']}",
        json={"primary_domain": alias},
        headers=_auth(editor),
    )
    assert patch_conflict.status_code == 400, patch_conflict.text
    assert patch_conflict.json()["error"]["code"] == "channel_domain_conflict"


def test_channel_list_scope_separates_publish_and_monitoring(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"channel-scope-{suffix}")
    editor = user_factory(f"channel-scope-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    publish = Channel(
        project_id=project.id,
        code=f"publish-{suffix}",
        name="发布渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
    )
    monitoring = Channel(
        project_id=project.id,
        code=f"monitor-{suffix}",
        name="监测渠道",
        category=ChannelCategory.COMMUNITY,
        status=ChannelStatus.OBSERVED,
    )
    db.add_all([publish, monitoring])
    db.flush()

    publish_resp = client.get(
        f"/api/v1/projects/{project.id}/channels?scope=publish&page_size=100",
        headers=_auth(editor),
    )
    assert publish_resp.status_code == 200
    publish_data = publish_resp.json()
    assert publish_data["meta"]["total"] == 1
    assert [row["code"] for row in publish_data["data"]] == [publish.code]

    monitoring_resp = client.get(
        f"/api/v1/projects/{project.id}/channels?scope=monitoring&page_size=100",
        headers=_auth(editor),
    )
    assert monitoring_resp.status_code == 200
    monitoring_data = monitoring_resp.json()
    assert monitoring_data["meta"]["total"] == 1
    assert [row["code"] for row in monitoring_data["data"]] == [monitoring.code]

    all_resp = client.get(
        f"/api/v1/projects/{project.id}/channels?page_size=100",
        headers=_auth(editor),
    )
    assert all_resp.status_code == 200
    assert all_resp.json()["meta"]["total"] == 2


def test_brand_governance_reports_domains_materials_and_channel_owners(
    client, db, project_factory, user_factory, member_factory
):
    """P14：域名、品牌口径、素材、渠道负责人四项必须能从接口自证。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"brand-governance-{suffix}")
    editor = user_factory(f"brand-governance-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    db.add(
        BrandProfile(
            project_id=project.id,
            canonical_name="广东省AI数字人才就业实训基地",
            aliases=["成才"],
            identifiers=["番山创业中心1号楼2区207"],
            owned_domains=["gdccai.com"],
            is_active=True,
        )
    )
    channel = Channel(
        project_id=project.id,
        code=f"gov-{suffix}",
        name="治理渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
        owner_name="渠道运营负责人",
        owner_contact="ops@example.com",
    )
    db.add(channel)
    db.add(
        Material(
            project_id=project.id,
            title="品牌口径与渠道责任说明",
            category=MaterialCategory.DOCUMENT,
            description="P14 品牌素材",
            file_name="brand-brief.md",
            content_type="text/markdown",
            byte_size=1024,
            checksum="a" * 64,
            storage_key=f"materials/{project.id}/brand-brief.md",
            created_by=editor.id,
        )
    )
    db.flush()

    response = client.get(
        f"/api/v1/projects/{project.id}/brand-profile/governance",
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["configured"] is True
    assert data["domains"] == ["gdccai.com"]
    assert data["materials_total"] == 1
    assert data["materials_by_category"] == {"document": 1}
    assert data["channels_total"] == 1
    assert data["channels_with_owner"] == 1
    assert data["channel_owners"] == [
        {"name": "渠道运营负责人", "contact": "ops@example.com", "channels": 1}
    ]
    assert data["ready"] is True
    assert data["missing"] == []


def test_delete_channel_only_for_unreferenced_candidate_with_audit_snapshot(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"channel-delete-{suffix}")
    editor = user_factory(f"channel-delete-editor-{suffix}")
    viewer = user_factory(f"channel-delete-viewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, viewer, RoleCode.VIEWER)

    created = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": f"remove-{suffix}",
            "name": "误建渠道",
            "category": "content_platform",
            "primary_domain": f"remove-{suffix}.example.com",
            "aliases": [f"old-{suffix}.example.com"],
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    channel_id = uuid.UUID(created.json()["data"]["id"])

    denied = client.delete(
        f"/api/v1/projects/{project.id}/channels/{channel_id}",
        headers=_auth(viewer),
    )
    assert denied.status_code == 403

    removed = client.delete(
        f"/api/v1/projects/{project.id}/channels/{channel_id}",
        headers=_auth(editor),
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"]["id"] == str(channel_id)
    assert removed.json()["data"]["deleted"] is True
    assert db.get(Channel, channel_id) is None
    assert db.scalars(
        select(ChannelAlias).where(ChannelAlias.channel_id == channel_id)
    ).all() == []

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.target_id == channel_id,
            AuditLog.action == "channel.delete",
        )
    )
    assert audit is not None
    assert audit.payload["channel"]["code"] == f"remove-{suffix}"
    assert audit.payload["channel"]["aliases"] == [
        {"domain": f"old-{suffix}.example.com", "alias_name": "误建渠道"}
    ]
    assert audit.payload["channel"]["approvals"]

    approved_candidate = Channel(
        project_id=project.id,
        code=f"approved-candidate-{suffix}",
        name="已准入但未使用渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
        approval_status=ChannelApprovalStatus.APPROVED,
    )
    db.add(approved_candidate)
    db.flush()
    removed_approved = client.delete(
        f"/api/v1/projects/{project.id}/channels/{approved_candidate.id}",
        headers=_auth(editor),
    )
    assert removed_approved.status_code == 200, removed_approved.text
    assert db.get(Channel, approved_candidate.id) is None

    observed = Channel(
        project_id=project.id,
        code=f"observed-{suffix}",
        name="已观测渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.OBSERVED,
    )
    db.add(observed)
    db.flush()
    refused_observed = client.delete(
        f"/api/v1/projects/{project.id}/channels/{observed.id}",
        headers=_auth(editor),
    )
    assert refused_observed.status_code == 409
    assert refused_observed.json()["error"]["code"] == "channel_not_deletable"

    referenced = Channel(
        project_id=project.id,
        code=f"referenced-{suffix}",
        name="有发布账号的渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
    )
    db.add(referenced)
    db.flush()
    db.add(
        PublishAccount(
            project_id=project.id,
            channel_id=referenced.id,
            account_name=f"account-{suffix}",
            credential_ref="vault://test/channel-delete",
            is_active=True,
        )
    )
    db.flush()
    refused_referenced = client.delete(
        f"/api/v1/projects/{project.id}/channels/{referenced.id}",
        headers=_auth(editor),
    )
    assert refused_referenced.status_code == 409
    assert refused_referenced.json()["error"]["code"] == "channel_in_use"
    assert "发布账号" in refused_referenced.json()["error"]["message"]

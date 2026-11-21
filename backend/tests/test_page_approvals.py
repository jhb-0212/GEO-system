"""页面级发布审批：独立招生/招聘页型、逐页台账与发布回执闸门。"""

import uuid

from app.core.security import create_access_token
from app.models import (
    Channel,
    PublishAccount,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    PublishTaskStatus,
    RoleCode,
)


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _channel_and_account(db, project, suffix, *, category=ChannelCategory.CONTENT_PLATFORM, domain="example.com"):
    channel = Channel(
        project_id=project.id,
        code=f"page-ch-{suffix}",
        name="页面审批测试渠道",
        category=category,
        status=ChannelStatus.OBSERVED,
        approval_status=ChannelApprovalStatus.APPROVED,
        primary_domain=domain,
        is_active=True,
    )
    db.add(channel)
    db.flush()
    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"page-acc-{suffix}",
        credential_ref="vault://test/publish",
        is_active=True,
    )
    db.add(account)
    db.flush()
    return channel, account


def _approved_channel_version(client, db, project, editor, reviewer, suffix, channel_id):
    parent = client.post(
        f"/api/v1/projects/{project.id}/contents",
        json={"title": f"页面审批母稿-{suffix}", "kind": "master"},
        headers=_auth(editor),
    )
    assert parent.status_code == 201, parent.text
    item = client.post(
        f"/api/v1/projects/{project.id}/contents",
        json={
            "title": f"页面审批渠道稿-{suffix}",
            "kind": "channel",
            "parent_id": parent.json()["data"]["item_id"],
            "channel_id": str(channel_id),
        },
        headers=_auth(editor),
    )
    assert item.status_code == 201, item.text
    version = client.post(
        f"/api/v1/projects/{project.id}/contents/{item.json()['data']['item_id']}/versions",
        json={"body": f"页面审批正文-{suffix}"},
        headers=_auth(editor),
    )
    assert version.status_code == 201, version.text
    version_id = version.json()["data"]["version_id"]
    assert client.post(
        f"/api/v1/projects/{project.id}/content-versions/{version_id}/submit",
        headers=_auth(editor),
    ).status_code == 200
    assert client.post(
        f"/api/v1/projects/{project.id}/content-versions/{version_id}/review",
        json={"decision": "approved", "comment": "通过"},
        headers=_auth(reviewer),
    ).status_code == 200
    return version_id


def _create_task(client, project, editor, version_id, channel_id, account_id):
    return client.post(
        f"/api/v1/projects/{project.id}/publish/tasks",
        json={
            "version_id": str(version_id),
            "channel_id": str(channel_id),
            "account_id": str(account_id),
            "task_key": f"page-{str(version_id)[:8]}",
        },
        headers=_auth(editor),
    )


def _set_publishing(db, task_id):
    task = db.get(PublishTask, uuid.UUID(task_id))
    task.status = PublishTaskStatus.PUBLISHING
    db.flush()


def _create_approval(client, project, editor, channel_id, page_url, *, page_type, permission="official", title=None):
    return client.post(
        f"/api/v1/projects/{project.id}/page-approvals",
        json={
            "channel_id": str(channel_id),
            "page_url": page_url,
            "title": title,
            "page_type": page_type,
            "permission": permission,
        },
        headers=_auth(editor),
    )


def _approve(client, project, admin, approval_id):
    return client.post(
        f"/api/v1/projects/{project.id}/page-approvals/{approval_id}/review",
        json={"decision": "approved", "note": "页面权属已核对"},
        headers=_auth(admin),
    )


def test_create_page_approval_validates_page_type_without_domain_lock(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"page-create-{suffix}")
    editor = user_factory(f"page-create-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, _ = _channel_and_account(db, project, suffix)

    other_domain = _create_approval(
        client,
        project,
        editor,
        channel.id,
        "https://other.example.net/admissions/2026",
        page_type="admissions",
        title="外部域名招生页",
    )
    assert other_domain.status_code == 201, other_domain.text
    assert other_domain.json()["data"]["status"] == "pending"

    mismatch_type = _create_approval(
        client,
        project,
        editor,
        channel.id,
        "https://example.com/admissions/2026",
        page_type="article",
    )
    assert mismatch_type.status_code == 422
    assert mismatch_type.json()["error"]["code"] == "page_approval_type_mismatch"

    created = _create_approval(
        client,
        project,
        editor,
        channel.id,
        "https://example.com/admissions/2026",
        page_type="admissions",
        title="2026 招生简章",
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["status"] == "pending"
    assert data["page_type"] == "admissions"
    assert data["can_publish"] is False

    duplicate = _create_approval(
        client,
        project,
        editor,
        channel.id,
        "http://example.com/admissions/2026?utm_source=test",
        page_type="admissions",
        title="2026 招生简章",
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "page_approval_exists"


def test_page_approval_allowed_without_channel_domain(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"page-nodomain-{suffix}")
    editor = user_factory(f"page-nodomain-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, _ = _channel_and_account(db, project, suffix, domain=None)

    response = _create_approval(
        client,
        project,
        editor,
        channel.id,
        "https://example.com/admissions/2026",
        page_type="admissions",
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["status"] == "pending"


def test_institution_channel_blocks_receipt_until_page_approved(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"page-inst-{suffix}")
    editor = user_factory(f"page-inst-editor-{suffix}")
    reviewer = user_factory(f"page-inst-reviewer-{suffix}")
    admin = user_factory(f"page-inst-admin-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    channel, account = _channel_and_account(
        db, project, suffix, category=ChannelCategory.INSTITUTION
    )
    version_id = _approved_channel_version(
        client, db, project, editor, reviewer, suffix, channel.id
    )
    created_task = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert created_task.status_code == 201, created_task.text
    task_id = created_task.json()["data"]["task_id"]
    _set_publishing(db, task_id)

    blocked = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/receipts",
        json={"published_url": "https://example.com/about-us"},
        headers=_auth(editor),
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "page_approval_required"

    approval = _create_approval(
        client,
        project,
        editor,
        channel.id,
        "https://example.com/about-us",
        page_type="article",
        permission="official",
    )
    assert approval.status_code == 201, approval.text
    approval_id = approval.json()["data"]["id"]
    assert _approve(client, project, admin, approval_id).status_code == 200

    receipt = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/receipts",
        json={"published_url": "https://example.com/about-us"},
        headers=_auth(editor),
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["data"]["status"] == "published"
    assert receipt.json()["data"]["page_approval_id"] == approval_id
    saved = db.get(PublishReceipt, uuid.UUID(receipt.json()["data"]["receipt_id"]))
    assert str(saved.page_approval_id) == approval_id

    detail = client.get(
        f"/api/v1/projects/{project.id}/page-approvals/{approval_id}",
        headers=_auth(editor),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["status"] == "approved"
    assert detail.json()["data"]["page_url"] == "https://example.com/about-us"

    with_approval = client.get(
        f"/api/v1/projects/{project.id}/publish/receipts?has_page_approval=true",
        headers=_auth(editor),
    )
    assert with_approval.status_code == 200, with_approval.text
    assert with_approval.json()["meta"]["total"] == 1
    without_approval = client.get(
        f"/api/v1/projects/{project.id}/publish/receipts?has_page_approval=false",
        headers=_auth(editor),
    )
    assert without_approval.status_code == 200
    assert without_approval.json()["meta"]["total"] == 0


def test_admissions_page_requires_approval_even_on_content_channel(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"page-adm-{suffix}")
    editor = user_factory(f"page-adm-editor-{suffix}")
    reviewer = user_factory(f"page-adm-reviewer-{suffix}")
    admin = user_factory(f"page-adm-admin-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(
        client, db, project, editor, reviewer, suffix, channel.id
    )
    created_task = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert created_task.status_code == 201, created_task.text
    task_id = created_task.json()["data"]["task_id"]
    _set_publishing(db, task_id)

    blocked = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/receipts",
        json={"published_url": "https://example.com/admissions/2026"},
        headers=_auth(editor),
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "page_approval_required"

    approval = _create_approval(
        client,
        project,
        editor,
        channel.id,
        "https://example.com/admissions/2026",
        page_type="admissions",
        title="2026 招生简章",
    )
    assert approval.status_code == 201, approval.text
    assert _approve(client, project, admin, approval.json()["data"]["id"]).status_code == 200

    receipt = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/receipts",
        json={"published_url": "https://example.com/admissions/2026"},
        headers=_auth(editor),
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["data"]["status"] == "published"


def test_third_party_page_approval_cannot_authorize_official_receipt(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"page-third-{suffix}")
    editor = user_factory(f"page-third-editor-{suffix}")
    reviewer = user_factory(f"page-third-reviewer-{suffix}")
    admin = user_factory(f"page-third-admin-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(
        client, db, project, editor, reviewer, suffix, channel.id
    )
    created_task = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert created_task.status_code == 201, created_task.text
    task_id = created_task.json()["data"]["task_id"]
    _set_publishing(db, task_id)

    approval = _create_approval(
        client,
        project,
        editor,
        channel.id,
        "https://example.com/admissions/third-party",
        page_type="admissions",
        permission="third_party",
        title="媒体转载招生页",
    )
    assert approval.status_code == 201, approval.text
    assert _approve(client, project, admin, approval.json()["data"]["id"]).status_code == 200

    receipt = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/receipts",
        json={"published_url": "https://example.com/admissions/third-party"},
        headers=_auth(editor),
    )
    assert receipt.status_code == 409
    assert receipt.json()["error"]["code"] == "page_approval_not_publishable"
    assert db.query(PublishReceipt).filter(PublishReceipt.task_id == uuid.UUID(task_id)).count() == 0


def test_verify_published_outcome_also_requires_page_approval(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"page-verify-{suffix}")
    editor = user_factory(f"page-verify-editor-{suffix}")
    reviewer = user_factory(f"page-verify-reviewer-{suffix}")
    admin = user_factory(f"page-verify-admin-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    channel, account = _channel_and_account(
        db, project, suffix, category=ChannelCategory.INSTITUTION
    )
    version_id = _approved_channel_version(
        client, db, project, editor, reviewer, suffix, channel.id
    )
    created_task = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert created_task.status_code == 201, created_task.text
    task_id = created_task.json()["data"]["task_id"]
    task = db.get(PublishTask, uuid.UUID(task_id))
    task.status = PublishTaskStatus.UNKNOWN
    db.flush()

    blocked = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/verify",
        json={"outcome": "published", "published_url": "https://example.com/verify-page"},
        headers=_auth(editor),
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "page_approval_required"

    approval = _create_approval(
        client,
        project,
        editor,
        channel.id,
        "https://example.com/verify-page",
        page_type="article",
    )
    assert approval.status_code == 201, approval.text
    approval_id = approval.json()["data"]["id"]
    assert _approve(client, project, admin, approval_id).status_code == 200

    verified = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/verify",
        json={"outcome": "published", "published_url": "https://example.com/verify-page"},
        headers=_auth(editor),
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["page_approval_id"] == approval_id
    assert verified.json()["data"]["receipt_id"]
    receipt = db.query(PublishReceipt).filter(PublishReceipt.task_id == uuid.UUID(task_id)).one()
    assert str(receipt.page_approval_id) == approval_id


def test_page_approval_review_revoke_state_machine(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"page-state-{suffix}")
    editor = user_factory(f"page-state-editor-{suffix}")
    admin = user_factory(f"page-state-admin-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    channel, _ = _channel_and_account(db, project, suffix)

    approval = _create_approval(
        client,
        project,
        editor,
        channel.id,
        "https://example.com/recruitment/2026",
        page_type="recruitment",
        title="2026 招聘岗位",
    )
    assert approval.status_code == 201, approval.text
    approval_id = approval.json()["data"]["id"]

    missing_note = client.post(
        f"/api/v1/projects/{project.id}/page-approvals/{approval_id}/review",
        json={"decision": "rejected"},
        headers=_auth(admin),
    )
    assert missing_note.status_code == 422

    approved = client.post(
        f"/api/v1/projects/{project.id}/page-approvals/{approval_id}/review",
        json={"decision": "approved", "note": "岗位信息已核对"},
        headers=_auth(admin),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "approved"
    assert approved.json()["data"]["can_publish"] is True

    repeated = client.post(
        f"/api/v1/projects/{project.id}/page-approvals/{approval_id}/review",
        json={"decision": "rejected", "note": "重复审批"},
        headers=_auth(admin),
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "page_approval_state_conflict"

    missing_revoke_note = client.post(
        f"/api/v1/projects/{project.id}/page-approvals/{approval_id}/revoke",
        json={"note": ""},
        headers=_auth(admin),
    )
    assert missing_revoke_note.status_code == 422

    revoked = client.post(
        f"/api/v1/projects/{project.id}/page-approvals/{approval_id}/revoke",
        json={"note": "招聘计划撤回"},
        headers=_auth(admin),
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["data"]["status"] == "revoked"
    assert revoked.json()["data"]["can_publish"] is False

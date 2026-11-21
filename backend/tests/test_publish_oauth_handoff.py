"""P56/P57：发布账号绑定 OAuth、令牌失效阻断、扫码/验证码转人工。"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from app.api import publishing as publishing_api
from app.core.secrets_box import encrypt_secret
from app.core.security import create_access_token
from app.models import (
    Channel,
    ContentItem,
    ContentVersion,
    OAuthConnection,
    PublishAccount,
    PublishAttempt,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import (
    AttemptResult,
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    ContentKind,
    ContentStatus,
    OAuthConnectionStatus,
    PublishTaskStatus,
    RoleCode,
)


def _auth(user):
    return {
        "Authorization": (
            f"Bearer {create_access_token(user.id, token_version=user.token_version)}"
        )
    }


def _channel(db, project, suffix, code):
    row = Channel(
        project_id=project.id,
        code=code,
        name=f"发布渠道-{suffix}",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.OBSERVED,
        approval_status=ChannelApprovalStatus.APPROVED,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _oauth_connection(
    db, project, channel, suffix, *, status=OAuthConnectionStatus.CONNECTED
):
    connection = OAuthConnection(
        project_id=project.id,
        channel_id=channel.id,
        provider_code=f"provider-{suffix}",
        external_account_id=f"external-{suffix}",
        external_account_name=f"平台账号-{suffix}",
        scopes=["publish"],
        status=status,
        access_token_encrypted=encrypt_secret(f"access-token-{suffix}"),
        refresh_token_encrypted=encrypt_secret(f"refresh-token-{suffix}"),
        connected_at=datetime.now(timezone.utc),
    )
    db.add(connection)
    db.flush()
    return connection


def _approved_version(db, project, channel, suffix):
    master = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title=f"授权母稿-{suffix}",
        status=ContentStatus.APPROVED,
    )
    db.add(master)
    db.flush()
    item = ContentItem(
        project_id=project.id,
        parent_id=master.id,
        channel_id=channel.id,
        kind=ContentKind.CHANNEL,
        title=f"授权渠道稿-{suffix}",
        status=ContentStatus.APPROVED,
    )
    db.add(item)
    db.flush()
    body = f"授权发布正文-{suffix}"
    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body=body,
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        status=ContentStatus.APPROVED,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.flush()
    return version


def _create_account(client, project, editor, channel, connection, suffix, *, name=None):
    return client.post(
        f"/api/v1/projects/{project.id}/publish/accounts",
        json={
            "channel_id": str(channel.id),
            "account_name": name or f"授权账号-{suffix}",
            "oauth_connection_id": str(connection.id),
        },
        headers=_auth(editor),
    )


def _create_task(
    client, project, editor, version, channel, account, suffix, *, mode="authorized"
):
    return client.post(
        f"/api/v1/projects/{project.id}/publish/tasks",
        json={
            "version_id": str(version.id),
            "channel_id": str(channel.id),
            "account_id": str(account.id),
            "publish_mode": mode,
            "task_key": f"auth-{suffix}",
        },
        headers=_auth(editor),
    )


class _FailIfCalledPublisher:
    def __init__(self, *args, **kwargs):
        raise AssertionError("授权预检不应调用公众号发布器")


def test_account_oauth_binding_validates_channel_and_uniqueness(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"oab-{suffix}")
    editor = user_factory(f"oab-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel = _channel(db, project, suffix, f"ch-a-{suffix}")
    other_channel = _channel(db, project, suffix, f"ch-b-{suffix}")
    connection = _oauth_connection(db, project, channel, suffix)

    mismatch = client.post(
        f"/api/v1/projects/{project.id}/publish/accounts",
        json={
            "channel_id": str(other_channel.id),
            "account_name": f"错渠道账号-{suffix}",
            "oauth_connection_id": str(connection.id),
        },
        headers=_auth(editor),
    )
    assert mismatch.status_code == 409, mismatch.text
    assert mismatch.json()["error"]["code"] == "oauth_channel_mismatch"

    first = _create_account(client, project, editor, channel, connection, suffix)
    assert first.status_code == 201, first.text
    data = first.json()["data"]
    assert data["oauth_connection_id"] == str(connection.id)
    assert data["oauth_status"] == "connected"

    listed = client.get(
        f"/api/v1/projects/{project.id}/publish/accounts",
        headers=_auth(editor),
    )
    assert listed.status_code == 200, listed.text
    listed_row = next(item for item in listed.json()["data"] if item["id"] == data["id"])
    assert listed_row["oauth_connection_id"] == str(connection.id)
    assert listed_row["oauth_provider_code"] == f"provider-{suffix}"
    assert "access_token" not in listed.text
    assert "refresh_token" not in listed.text

    duplicate = _create_account(
        client, project, editor, channel, connection, suffix, name=f"重复绑定-{suffix}"
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "publish_account_oauth_in_use"

    cleared = client.patch(
        f"/api/v1/projects/{project.id}/publish/accounts/{data['id']}",
        json={"oauth_connection_id": None},
        headers=_auth(editor),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["oauth_connection_id"] is None


def test_authorized_task_with_revoked_oauth_hands_off_without_external_call(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"oar-{suffix}")
    editor = user_factory(f"oar-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel = _channel(db, project, suffix, f"ch-r-{suffix}")
    connection = _oauth_connection(db, project, channel, suffix)
    version = _approved_version(db, project, channel, suffix)
    account_resp = _create_account(client, project, editor, channel, connection, suffix)
    assert account_resp.status_code == 201, account_resp.text
    account = db.get(PublishAccount, uuid.UUID(account_resp.json()["data"]["id"]))
    task_resp = _create_task(client, project, editor, version, channel, account, suffix)
    assert task_resp.status_code == 201, task_resp.text
    task_id = uuid.UUID(task_resp.json()["data"]["task_id"])

    connection.status = OAuthConnectionStatus.REVOKED
    connection.revoked_at = datetime.now(timezone.utc)
    db.flush()
    monkeypatch.setattr(publishing_api, "WeChatOfficialPublisher", _FailIfCalledPublisher)

    first = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )
    assert first.status_code == 200, first.text
    result = first.json()["data"]
    assert result["status"] == "needs_review"
    assert result["manual_handoff"] is True
    assert result["handoff_reason"] == "oauth_connection_revoked"

    second = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["attempt_id"] == result["attempt_id"]

    db.expire_all()
    task = db.get(PublishTask, task_id)
    assert task.status == PublishTaskStatus.NEEDS_REVIEW
    attempts = db.query(PublishAttempt).filter(PublishAttempt.task_id == task_id).all()
    assert len(attempts) == 1
    assert attempts[0].result == AttemptResult.FAILED
    assert attempts[0].error_code == "oauth_connection_revoked"
    assert db.query(PublishReceipt).filter(PublishReceipt.task_id == task_id).count() == 0


def test_authorized_task_with_expired_oauth_hands_off_session_expired(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"oae-{suffix}")
    editor = user_factory(f"oae-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel = _channel(db, project, suffix, f"ch-e-{suffix}")
    connection = _oauth_connection(db, project, channel, suffix)
    connection.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.flush()
    version = _approved_version(db, project, channel, suffix)
    account_resp = _create_account(client, project, editor, channel, connection, suffix)
    assert account_resp.status_code == 201, account_resp.text
    account = db.get(PublishAccount, uuid.UUID(account_resp.json()["data"]["id"]))
    task = _create_task(client, project, editor, version, channel, account, suffix)
    assert task.status_code == 201, task.text
    task_id = task.json()["data"]["task_id"]
    monkeypatch.setattr(publishing_api, "WeChatOfficialPublisher", _FailIfCalledPublisher)

    result = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["status"] == "needs_review"
    assert data["handoff_reason"] == "oauth_token_expired"
    assert data["manual_handoff"] is True


def test_authorized_task_with_valid_oauth_hands_off_browser_session(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"oav-{suffix}")
    editor = user_factory(f"oav-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel = _channel(db, project, suffix, f"ch-v-{suffix}")
    connection = _oauth_connection(db, project, channel, suffix)
    version = _approved_version(db, project, channel, suffix)
    account_resp = _create_account(client, project, editor, channel, connection, suffix)
    assert account_resp.status_code == 201, account_resp.text
    account = db.get(PublishAccount, uuid.UUID(account_resp.json()["data"]["id"]))
    task = _create_task(client, project, editor, version, channel, account, suffix)
    assert task.status_code == 201, task.text
    task_id = task.json()["data"]["task_id"]
    monkeypatch.setattr(publishing_api, "WeChatOfficialPublisher", _FailIfCalledPublisher)

    result = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["status"] == "needs_review"
    assert data["handoff_reason"] == "browser_session_required"
    assert data["manual_handoff"] is True


def test_handoff_captcha_is_idempotent_and_can_close_manually(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"ohd-{suffix}")
    editor = user_factory(f"ohd-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel = _channel(db, project, suffix, f"ch-h-{suffix}")
    connection = _oauth_connection(db, project, channel, suffix)
    version = _approved_version(db, project, channel, suffix)
    account_resp = _create_account(client, project, editor, channel, connection, suffix)
    assert account_resp.status_code == 201, account_resp.text
    account = db.get(PublishAccount, uuid.UUID(account_resp.json()["data"]["id"]))
    task = _create_task(client, project, editor, version, channel, account, suffix)
    assert task.status_code == 201, task.text
    task_id = task.json()["data"]["task_id"]

    first = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/handoff",
        json={"reason": "captcha_required", "note": "平台弹出验证码"},
        headers=_auth(editor),
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["status"] == "needs_review"
    assert first.json()["data"]["reason"] == "captcha_required"

    listed = client.get(
        f"/api/v1/projects/{project.id}/publish/tasks",
        headers=_auth(editor),
    )
    assert listed.status_code == 200, listed.text
    listed_row = next(item for item in listed.json()["data"] if item["id"] == task_id)
    assert listed_row["publish_mode"] == "authorized"
    assert listed_row["handoff_reason"] == "captcha_required"

    second = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/handoff",
        json={"reason": "captcha_required", "note": "平台弹出验证码"},
        headers=_auth(editor),
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["attempt_id"] == first.json()["data"]["attempt_id"]

    db.expire_all()
    attempts = (
        db.query(PublishAttempt)
        .filter(PublishAttempt.task_id == uuid.UUID(task_id))
        .all()
    )
    assert len(attempts) == 1

    success = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/attempts",
        json={"result": "success", "mode": "manual"},
        headers=_auth(editor),
    )
    assert success.status_code == 201, success.text
    assert success.json()["data"]["task_status"] == "publishing"

    receipt = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/receipts",
        json={"published_url": "https://example.com/post/handoff-close"},
        headers=_auth(editor),
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["data"]["status"] == "published"


def test_handoff_other_reason_requires_note(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"ohn-{suffix}")
    editor = user_factory(f"ohn-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel = _channel(db, project, suffix, f"ch-n-{suffix}")
    version = _approved_version(db, project, channel, suffix)
    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"人工账号-{suffix}",
        is_active=True,
    )
    db.add(account)
    db.flush()
    task = _create_task(
        client, project, editor, version, channel, account, suffix, mode="manual"
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["data"]["task_id"]

    missing_note = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/handoff",
        json={"reason": "other"},
        headers=_auth(editor),
    )
    assert missing_note.status_code == 422, missing_note.text


def test_handoff_requires_publish_execute_permission(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"ohp-{suffix}")
    editor = user_factory(f"ohp-editor-{suffix}")
    viewer = user_factory(f"ohp-viewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, viewer, RoleCode.VIEWER)
    channel = _channel(db, project, suffix, f"ch-p-{suffix}")
    version = _approved_version(db, project, channel, suffix)
    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"权限账号-{suffix}",
        is_active=True,
    )
    db.add(account)
    db.flush()
    task = _create_task(
        client, project, editor, version, channel, account, suffix, mode="manual"
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["data"]["task_id"]

    denied = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/handoff",
        json={"reason": "captcha_required"},
        headers=_auth(viewer),
    )
    assert denied.status_code == 403, denied.text


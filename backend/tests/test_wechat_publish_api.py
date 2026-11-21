"""微信公众号官方执行接口：成功结案、配置缺失、人工任务拒绝三条路径。"""

from __future__ import annotations

import hashlib
import uuid

from app.api import publishing as publishing_api
from app.core.config import settings
from app.core.security import create_access_token
from app.models import (
    Channel,
    ContentItem,
    ContentVersion,
    PublishAccount,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    ContentKind,
    ContentStatus,
    PublishMode,
    PublishTaskStatus,
    RoleCode,
)
from app.services.wechat_publisher import WeChatPublishResult, WeChatPublisherError


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _wechat_version(db, project, suffix):
    channel = Channel(
        project_id=project.id,
        code="wechat-mp",
        name="微信公众号",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.OBSERVED,
        approval_status=ChannelApprovalStatus.APPROVED,
        is_active=True,
    )
    db.add(channel)
    db.flush()
    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"公众号账号-{suffix}",
        credential_ref="WECHAT_MP_SECRET_KEY",
        is_active=True,
    )
    master = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title=f"公众号母稿-{suffix}",
        status=ContentStatus.APPROVED,
    )
    db.add_all([account, master])
    db.flush()
    item = ContentItem(
        project_id=project.id,
        parent_id=master.id,
        channel_id=channel.id,
        kind=ContentKind.CHANNEL,
        title=f"公众号测试稿-{suffix}",
        status=ContentStatus.APPROVED,
    )
    db.add(item)
    db.flush()
    body = "# 测试标题\n\n正文第一段"
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
    return channel, account, item, version


def _create_api_task(client, project, editor, version, channel, account, suffix):
    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks",
        json={
            "version_id": str(version.id),
            "channel_id": str(channel.id),
            "account_id": str(account.id),
            "publish_mode": "api",
            "task_key": f"wechat-{suffix}",
        },
        headers=_auth(editor),
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["data"]["task_id"])


class _FakePublisher:
    def __init__(self, app_id, app_secret, **kwargs):
        self.app_id = app_id
        self.app_secret = app_secret

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def publish_article(self, **kwargs):
        return WeChatPublishResult(
            media_id="media-test",
            publish_id="publish-test",
            article_url="https://mp.weixin.qq.com/s/test",
            raw={"media_id": "media-test"},
        )


class _CountingPublisher(_FakePublisher):
    calls = 0

    def publish_article(self, **kwargs):
        type(self).calls += 1
        return super().publish_article(**kwargs)


class _AmbiguousPublisher(_FakePublisher):
    def publish_article(self, **kwargs):
        raise WeChatPublisherError(
            "timeout after submit",
            code="wechat_network_unknown",
            ambiguous=True,
            retryable=True,
        )


class _RejectedPublisher(_FakePublisher):
    def publish_article(self, **kwargs):
        raise WeChatPublisherError(
            "api unauthorized",
            code="wechat_api_unauthorized",
            errcode=48001,
        )


def test_execute_wechat_publishes_and_closes_with_receipt(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"wx-{suffix}")
    editor = user_factory(f"wx-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account, _, version = _wechat_version(db, project, suffix)
    task_id = _create_api_task(client, project, editor, version, channel, account, suffix)

    monkeypatch.setattr(settings, "wechat_mp_app_id", "wx-app-id")
    monkeypatch.setattr(publishing_api, "read_credential_env", lambda ref: "wx-secret")
    monkeypatch.setattr(publishing_api, "WeChatOfficialPublisher", _FakePublisher)

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={"thumb_media_id": "thumb-test"},
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "published"
    assert data["article_url"] == "https://mp.weixin.qq.com/s/test"
    assert data["receipt_id"]

    task = db.get(PublishTask, task_id)
    assert task.status == PublishTaskStatus.PUBLISHED
    assert task.external_task_id == "publish-test"
    receipts = db.query(PublishReceipt).filter(PublishReceipt.task_id == task_id).all()
    assert len(receipts) == 1
    assert receipts[0].published_url == "https://mp.weixin.qq.com/s/test"


def test_execute_duplicate_call_does_not_send_twice(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"wxdup-{suffix}")
    editor = user_factory(f"wxdup-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account, _, version = _wechat_version(db, project, suffix)
    task_id = _create_api_task(client, project, editor, version, channel, account, suffix)

    _CountingPublisher.calls = 0
    monkeypatch.setattr(settings, "wechat_mp_app_id", "wx-app-id")
    monkeypatch.setattr(publishing_api, "read_credential_env", lambda ref: "wx-secret")
    monkeypatch.setattr(publishing_api, "WeChatOfficialPublisher", _CountingPublisher)

    first = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["status"] == "published"
    assert _CountingPublisher.calls == 1

    second = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )
    assert second.status_code == 409, second.text
    assert _CountingPublisher.calls == 1

    db.expire_all()
    task = db.get(PublishTask, task_id)
    assert task.status == PublishTaskStatus.PUBLISHED
    receipts = db.query(PublishReceipt).filter(PublishReceipt.task_id == task_id).all()
    assert len(receipts) == 1


def test_execute_wechat_requires_configured_credentials(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"wxcfg-{suffix}")
    editor = user_factory(f"wxcfg-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account, _, version = _wechat_version(db, project, suffix)
    task_id = _create_api_task(client, project, editor, version, channel, account, suffix)

    monkeypatch.setattr(settings, "wechat_mp_app_id", "")
    monkeypatch.setattr(publishing_api, "read_credential_env", lambda ref: "")

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "wechat_mp_not_configured"
    assert db.get(PublishTask, task_id).status == PublishTaskStatus.PENDING


def test_execute_wechat_rejection_marks_failed(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"wxbad-{suffix}")
    editor = user_factory(f"wxbad-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account, _, version = _wechat_version(db, project, suffix)
    task_id = _create_api_task(client, project, editor, version, channel, account, suffix)

    monkeypatch.setattr(settings, "wechat_mp_app_id", "wx-app-id")
    monkeypatch.setattr(publishing_api, "read_credential_env", lambda ref: "wx-secret")
    monkeypatch.setattr(publishing_api, "WeChatOfficialPublisher", _RejectedPublisher)

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "failed"
    assert data["error_code"] == "wechat_api_unauthorized"
    task = db.get(PublishTask, task_id)
    assert task.status == PublishTaskStatus.FAILED
    assert db.get(ContentVersion, version.id).status == ContentStatus.NEEDS_ATTENTION


def test_execute_wechat_timeout_marks_unknown(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"wxunk-{suffix}")
    editor = user_factory(f"wxunk-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account, _, version = _wechat_version(db, project, suffix)
    task_id = _create_api_task(client, project, editor, version, channel, account, suffix)

    monkeypatch.setattr(settings, "wechat_mp_app_id", "wx-app-id")
    monkeypatch.setattr(publishing_api, "read_credential_env", lambda ref: "wx-secret")
    monkeypatch.setattr(publishing_api, "WeChatOfficialPublisher", _AmbiguousPublisher)

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "unknown"
    assert data["error_code"] == "wechat_network_unknown"
    task = db.get(PublishTask, task_id)
    assert task.status == PublishTaskStatus.UNKNOWN
    assert db.get(ContentVersion, version.id).status == ContentStatus.NEEDS_ATTENTION


def test_execute_rejects_manual_task(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"wxman-{suffix}")
    editor = user_factory(f"wxman-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account, _, version = _wechat_version(db, project, suffix)
    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks",
        json={
            "version_id": str(version.id),
            "channel_id": str(channel.id),
            "account_id": str(account.id),
            "publish_mode": PublishMode.MANUAL.value,
            "task_key": f"manual-{suffix}",
        },
        headers=_auth(editor),
    )
    task_id = resp.json()["data"]["task_id"]
    out = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )
    assert out.status_code == 409
    assert "官方 API 模式" in out.json()["error"]["message"]

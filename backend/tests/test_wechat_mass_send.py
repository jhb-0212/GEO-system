"""公众号群发接口：独立开关、只允许人工、异步不结案、绝不自动重试。

群发与 freepublish 的差别（也是本文件的断言重点）：
- 默认关闭（`WECHAT_MP_MASS_SEND_ENABLED=false`），关闭时零外部调用；
- 只在人工触发时可用，Celery 调度器永远只走 freepublish；
- 提交成功没有文章 URL，只能停在 publishing，等运营补回执结案；
- 平台明确失败落 failed，超时/5xx 落 unknown，不重试。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.core.errors import ReviewStateError
from app.core.security import create_access_token
from app.models import (
    AuditLog,
    Channel,
    ContentItem,
    ContentVersion,
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
    PublishMode,
    PublishTaskStatus,
    RoleCode,
)
from app.services import publish_execution
from app.services.publish_execution import (
    PublishDelivery,
    _mass_clientmsgid,
    execute_wechat_publish,
    run_due_wechat_publishes,
)
from app.services.wechat_publisher import (
    WeChatMassSendResult,
    WeChatPublishResult,
    WeChatPublisherError,
)


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _fixture(db, project, suffix: str, *, mode=PublishMode.API, channel_code=None):
    channel = Channel(
        project_id=project.id,
        code=channel_code or settings.wechat_mp_channel_code,
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
        account_name=f"群发账号-{suffix}",
        credential_ref="WECHAT_MP_SECRET_KEY",
        is_active=True,
    )
    master = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title=f"群发母稿-{suffix}",
        status=ContentStatus.APPROVED,
    )
    db.add_all([account, master])
    db.flush()
    item = ContentItem(
        project_id=project.id,
        parent_id=master.id,
        channel_id=channel.id,
        kind=ContentKind.CHANNEL,
        title=f"群发稿-{suffix}",
        status=ContentStatus.APPROVED,
    )
    db.add(item)
    db.flush()
    body = "# 群发标题\n\n正文"
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
    task = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"mass-{suffix}",
        idempotency_key=f"mass-{suffix}",
        publish_mode=mode,
        status=PublishTaskStatus.PENDING,
        entered_todo_at=datetime.now(timezone.utc),
    )
    db.add(task)
    db.flush()
    return channel, account, version, task


class _MassPublisher:
    calls = 0
    clientmsgids: list[str] = []

    def __init__(self, app_id, app_secret, **kwargs):
        self.app_id = app_id
        self.app_secret = app_secret

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def mass_send_article(self, **kwargs):
        type(self).calls += 1
        type(self).clientmsgids.append(kwargs.get("clientmsgid", ""))
        return WeChatMassSendResult(
            media_id="mass-media",
            msg_id="1000000001",
            msg_status="SENDING",
            status_note=None,
        )

    def publish_article(self, **kwargs):  # 不允许群发路径调用 freepublish
        raise AssertionError("群发分支不应调用 freepublish")


class _DeduplicatedPublisher(_MassPublisher):
    def mass_send_article(self, **kwargs):
        type(self).calls += 1
        return WeChatMassSendResult(
            media_id="mass-media",
            msg_id="1000000002",
            deduplicated=True,
            status_note="clientmsgid_deduplicated",
        )


class _FailedStatusPublisher(_MassPublisher):
    def mass_send_article(self, **kwargs):
        type(self).calls += 1
        return WeChatMassSendResult(
            media_id="mass-media",
            msg_id="1000000003",
            msg_status="SEND_FAIL",
            status_note="send fail",
        )


class _RejectedPublisher(_MassPublisher):
    def mass_send_article(self, **kwargs):
        type(self).calls += 1
        raise WeChatPublisherError(
            "api unauthorized",
            code="wechat_api_unauthorized",
            errcode=48001,
        )


class _AmbiguousPublisher(_MassPublisher):
    def mass_send_article(self, **kwargs):
        type(self).calls += 1
        raise WeChatPublisherError(
            "timeout after submit",
            code="wechat_network_unknown",
            ambiguous=True,
            retryable=True,
        )


def _patch(monkeypatch, publisher=_MassPublisher, *, enabled: bool = True):
    monkeypatch.setattr(settings, "wechat_mp_app_id", "wx-app-id")
    monkeypatch.setattr(settings, "wechat_mp_mass_send_enabled", enabled)
    monkeypatch.setattr(publish_execution, "read_credential_env", lambda ref: "wx-secret")
    monkeypatch.setattr(publish_execution, "WeChatOfficialPublisher", publisher)
    publisher.calls = 0


# ---------- service ----------


def test_switch_off_rejects_without_any_external_call(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-off-{suffix}")
    _, _, _, task = _fixture(db, project, suffix)
    db.commit()
    _patch(monkeypatch, enabled=False)

    with pytest.raises(ReviewStateError) as error:
        execute_wechat_publish(
            db,
            project_id=project.id,
            task_id=task.id,
            actor_id=None,
            delivery=PublishDelivery.MASS_SEND,
        )

    assert error.value.code == "wechat_mass_send_disabled"
    assert _MassPublisher.calls == 0
    db.expire_all()
    assert db.get(PublishTask, task.id).status == PublishTaskStatus.PENDING


def test_mass_send_submits_and_stays_publishing(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-ok-{suffix}")
    _, _, version, task = _fixture(db, project, suffix)
    db.commit()
    _patch(monkeypatch)

    result = execute_wechat_publish(
        db,
        project_id=project.id,
        task_id=task.id,
        actor_id=None,
        delivery=PublishDelivery.MASS_SEND,
    )

    assert result["delivery"] == "mass_send"
    assert result["status"] == PublishTaskStatus.PUBLISHING.value
    assert result["msg_id"] == "1000000001"
    assert result["media_id"] == "mass-media"
    assert result["article_url"] is None
    assert result["receipt_id"] is None
    assert result["next_action"]
    assert _MassPublisher.calls == 1
    # clientmsgid 必须存在且不超过微信 32 字节限制
    assert len(_MassPublisher.clientmsgids[-1].encode("utf-8")) <= 32

    db.expire_all()
    stored = db.get(PublishTask, task.id)
    assert stored.status == PublishTaskStatus.PUBLISHING
    assert stored.external_task_id == "1000000001"
    attempt = db.query(PublishAttempt).filter(PublishAttempt.task_id == task.id).one()
    assert attempt.result == AttemptResult.SUCCESS
    assert (
        db.query(PublishReceipt).filter(PublishReceipt.task_id == task.id).count() == 0
    )
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.target_id == task.id, AuditLog.action == "publish.wechat_mass_send")
        .one()
    )
    assert audit.payload["delivery"] == "mass_send"
    assert audit.payload["msg_id"] == "1000000001"
    assert audit.payload["trigger"] == "scheduler"


def test_clientmsgid_is_stable_per_version_and_bounded():
    project_id = uuid.uuid4()
    version_id = uuid.uuid4()
    first = _mass_clientmsgid(project_id, version_id)
    second = _mass_clientmsgid(project_id, version_id)
    other = _mass_clientmsgid(project_id, uuid.uuid4())
    assert first == second
    assert first != other
    assert len(first) == 32


def test_duplicate_clientmsgid_reuses_existing_msg_id(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-dup-{suffix}")
    _, _, _, task = _fixture(db, project, suffix)
    db.commit()
    _patch(monkeypatch, _DeduplicatedPublisher)

    result = execute_wechat_publish(
        db,
        project_id=project.id,
        task_id=task.id,
        actor_id=None,
        delivery=PublishDelivery.MASS_SEND,
    )

    assert result["status"] == PublishTaskStatus.PUBLISHING.value
    assert result["msg_id"] == "1000000002"
    assert result["status_note"] == "clientmsgid_deduplicated"


def test_platform_send_fail_marks_failed(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-fail-{suffix}")
    _, _, version, task = _fixture(db, project, suffix)
    db.commit()
    _patch(monkeypatch, _FailedStatusPublisher)

    result = execute_wechat_publish(
        db,
        project_id=project.id,
        task_id=task.id,
        actor_id=None,
        delivery=PublishDelivery.MASS_SEND,
    )

    assert result["status"] == PublishTaskStatus.FAILED.value
    assert result["error_code"] == "wechat_mass_send_failed"
    db.expire_all()
    attempt = db.query(PublishAttempt).filter(PublishAttempt.task_id == task.id).one()
    assert attempt.result == AttemptResult.FAILED
    assert db.get(ContentVersion, version.id).status == ContentStatus.NEEDS_ATTENTION


def test_platform_rejection_marks_failed_without_retry(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-reject-{suffix}")
    _, _, _, task = _fixture(db, project, suffix)
    db.commit()
    _patch(monkeypatch, _RejectedPublisher)

    result = execute_wechat_publish(
        db,
        project_id=project.id,
        task_id=task.id,
        actor_id=None,
        delivery=PublishDelivery.MASS_SEND,
    )

    assert result["status"] == PublishTaskStatus.FAILED.value
    assert result["error_code"] == "wechat_api_unauthorized"
    assert _RejectedPublisher.calls == 1
    attempt = db.query(PublishAttempt).filter(PublishAttempt.task_id == task.id).one()
    assert attempt.error_code == "wechat_api_unauthorized"


def test_timeout_after_submit_lands_unknown(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-unknown-{suffix}")
    _, _, _, task = _fixture(db, project, suffix)
    db.commit()
    _patch(monkeypatch, _AmbiguousPublisher)

    result = execute_wechat_publish(
        db,
        project_id=project.id,
        task_id=task.id,
        actor_id=None,
        delivery=PublishDelivery.MASS_SEND,
    )

    assert result["status"] == PublishTaskStatus.UNKNOWN.value
    assert result["error_code"] == "wechat_network_unknown"


def test_manual_task_cannot_mass_send(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-manual-{suffix}")
    _, _, _, task = _fixture(db, project, suffix, mode=PublishMode.MANUAL)
    db.commit()
    _patch(monkeypatch)

    with pytest.raises(ReviewStateError):
        execute_wechat_publish(
            db,
            project_id=project.id,
            task_id=task.id,
            actor_id=None,
            delivery=PublishDelivery.MASS_SEND,
        )
    assert _MassPublisher.calls == 0


def test_non_wechat_channel_cannot_mass_send(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-toutiao-{suffix}")
    _, _, _, task = _fixture(db, project, suffix, channel_code="toutiao")
    db.commit()
    _patch(monkeypatch)

    with pytest.raises(ReviewStateError):
        execute_wechat_publish(
            db,
            project_id=project.id,
            task_id=task.id,
            actor_id=None,
            delivery=PublishDelivery.MASS_SEND,
        )
    assert _MassPublisher.calls == 0


def test_scheduler_only_uses_freepublish(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-sched-{suffix}")
    _, _, _, task = _fixture(db, project, suffix)
    task.scheduled_at = datetime.now(timezone.utc)
    db.commit()

    seen: list[str] = []

    def _fake_execute(db_, *, task_id, project_id, actor_id, delivery, **_kwargs):
        seen.append(delivery.value)
        return {"status": PublishTaskStatus.PUBLISHED.value}

    monkeypatch.setattr(settings, "publish_auto_execute_enabled", True)
    monkeypatch.setattr(publish_execution, "execute_wechat_publish", _fake_execute)

    stats = run_due_wechat_publishes(db)

    assert stats["due"] == 1
    assert seen == ["freepublish"]


class _NoUrlPublisher(_MassPublisher):
    def publish_article(self, **kwargs):
        type(self).calls += 1
        return WeChatPublishResult(
            media_id="free-media",
            publish_id="free-publish",
            article_url=None,
            status_note="wechat_publish_status_pending",
        )


def test_freepublish_without_url_stays_publishing(db, project_factory, monkeypatch):
    """freepublish 提交成功但拿不到 URL 时只能停在 publishing，不能因重复迁移报错。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"free-nourl-{suffix}")
    _, _, _, task = _fixture(db, project, suffix)
    db.commit()
    _patch(monkeypatch, _NoUrlPublisher)

    result = execute_wechat_publish(
        db,
        project_id=project.id,
        task_id=task.id,
        actor_id=None,
        delivery=PublishDelivery.FREEPUBLISH,
    )

    assert result["status"] == PublishTaskStatus.PUBLISHING.value
    assert result["receipt_id"] is None
    db.expire_all()
    assert db.get(PublishTask, task.id).status == PublishTaskStatus.PUBLISHING


# ---------- HTTP ----------


def _create_api_task(client, project, editor, version, channel, account, suffix):
    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks",
        json={
            "version_id": str(version.id),
            "channel_id": str(channel.id),
            "account_id": str(account.id),
            "publish_mode": "api",
            "task_key": f"mass-api-{suffix}",
        },
        headers=_auth(editor),
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["data"]["task_id"])


def test_mass_send_endpoint_409_when_switch_off(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-api-off-{suffix}")
    editor = user_factory(f"mass-api-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account, version, _ = _fixture(db, project, suffix)
    task_id = _create_api_task(client, project, editor, version, channel, account, suffix)
    db.commit()
    _patch(monkeypatch, enabled=False)

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/mass-send",
        json={},
        headers=_auth(editor),
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "wechat_mass_send_disabled"
    assert _MassPublisher.calls == 0


def test_mass_send_endpoint_requires_publish_permission(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-api-viewer-{suffix}")
    editor = user_factory(f"mass-api-editor-{suffix}")
    viewer = user_factory(f"mass-api-viewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, viewer, RoleCode.VIEWER)
    channel, account, version, _ = _fixture(db, project, suffix)
    # 建任务需要 publish.execute，用编辑建单；再用只读账号尝试群发。
    task_id = _create_api_task(client, project, editor, version, channel, account, suffix)
    db.commit()
    _patch(monkeypatch)

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/mass-send",
        json={},
        headers=_auth(viewer),
    )

    assert resp.status_code == 403, resp.text
    assert _MassPublisher.calls == 0


def test_mass_send_endpoint_success_returns_msg_id(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-api-ok-{suffix}")
    editor = user_factory(f"mass-api-ok-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account, version, _ = _fixture(db, project, suffix)
    task_id = _create_api_task(client, project, editor, version, channel, account, suffix)
    db.commit()
    _patch(monkeypatch)

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/mass-send",
        json={"thumb_media_id": "thumb-mass"},
        headers=_auth(editor),
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["delivery"] == "mass_send"
    assert data["status"] == "publishing"
    assert data["msg_id"] == "1000000001"
    assert data["receipt_id"] is None
    assert "receipts" in (data["next_action"] or "")


def test_execute_endpoint_reports_freepublish_delivery(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mass-api-free-{suffix}")
    editor = user_factory(f"mass-api-free-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account, version, _ = _fixture(db, project, suffix)
    task_id = _create_api_task(client, project, editor, version, channel, account, suffix)
    db.commit()
    monkeypatch.setattr(settings, "wechat_mp_app_id", "wx-app-id")
    monkeypatch.setattr(publish_execution, "read_credential_env", lambda ref: "wx-secret")

    class _FreePublisher(_MassPublisher):
        def publish_article(self, **kwargs):
            return WeChatPublishResult(
                media_id="free-media",
                publish_id="free-publish",
                article_url="https://mp.weixin.qq.com/s/free",
                raw={},
            )

    monkeypatch.setattr(publish_execution, "WeChatOfficialPublisher", _FreePublisher)

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/execute",
        json={},
        headers=_auth(editor),
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["delivery"] == "freepublish"
    assert data["status"] == "published"
    assert data["msg_id"] is None
    assert data["receipt_id"]

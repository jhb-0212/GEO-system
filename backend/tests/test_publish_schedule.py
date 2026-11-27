"""到点自动发稿：只认「显式排期 + api 模式 + 公众号渠道」，其余一律不动。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models import (
    Channel,
    ContentItem,
    ContentVersion,
    PublishAccount,
    PublishAttempt,
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
)
from app.services import publish_execution
from app.services.publish_execution import run_due_wechat_publishes
from app.services.wechat_publisher import WeChatPublishResult, WeChatPublisherError


class _FakePublisher:
    calls = 0

    def __init__(self, app_id, app_secret, **kwargs):
        self.app_id = app_id
        self.app_secret = app_secret

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def publish_article(self, **kwargs):
        type(self).calls += 1
        return WeChatPublishResult(
            media_id="media-sched",
            publish_id="publish-sched",
            article_url=f"https://mp.weixin.qq.com/s/{uuid.uuid4().hex[:8]}",
            raw={"media_id": "media-sched"},
        )


class _RejectedPublisher(_FakePublisher):
    def publish_article(self, **kwargs):
        raise WeChatPublisherError("api unauthorized", code="wechat_api_unauthorized", errcode=48001)


def _fixture(db, project, suffix: str, *, status=ContentStatus.APPROVED):
    channel = Channel(
        project_id=project.id,
        code=settings.wechat_mp_channel_code,
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
        title=f"母稿-{suffix}",
        status=ContentStatus.APPROVED,
    )
    db.add_all([account, master])
    db.flush()
    item = ContentItem(
        project_id=project.id,
        parent_id=master.id,
        channel_id=channel.id,
        kind=ContentKind.CHANNEL,
        title=f"渠道稿-{suffix}",
        status=status,
    )
    db.add(item)
    db.flush()
    body = "# 排期发稿\n\n正文"
    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body=body,
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        status=status,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.flush()
    return channel, account, version


def _task(db, project, version, channel, account, suffix: str, **overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "project_id": project.id,
        "version_id": version.id,
        "channel_id": channel.id,
        "account_id": account.id,
        "task_key": f"sched-{suffix}",
        "idempotency_key": f"sched-{suffix}",
        "publish_mode": PublishMode.API,
        "status": PublishTaskStatus.PENDING,
        "scheduled_at": now - timedelta(minutes=5),
        "entered_todo_at": now,
    }
    payload.update(overrides)
    task = PublishTask(**payload)
    db.add(task)
    db.flush()
    return task


def _patch_publisher(monkeypatch, publisher=_FakePublisher):
    monkeypatch.setattr(settings, "wechat_mp_app_id", "wx-app-id")
    monkeypatch.setattr(settings, "publish_auto_execute_enabled", True)
    monkeypatch.setattr(publish_execution, "read_credential_env", lambda ref: "wx-secret")
    monkeypatch.setattr(publish_execution, "WeChatOfficialPublisher", publisher)


def test_due_task_publishes_and_writes_receipt(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sched-{suffix}")
    channel, account, version = _fixture(db, project, suffix)
    task = _task(db, project, version, channel, account, suffix)
    db.commit()
    _patch_publisher(monkeypatch, _FakePublisher)
    _FakePublisher.calls = 0

    stats = run_due_wechat_publishes(db)

    assert stats["due"] == 1
    assert stats["published"] == 1
    db.refresh(task)
    assert task.status == PublishTaskStatus.PUBLISHED
    receipt = db.query(PublishReceipt).filter(PublishReceipt.task_id == task.id).one()
    assert receipt.published_url.startswith("https://mp.weixin.qq.com/s/")
    assert receipt.verified_by is None  # 系统触发，没有操作人


def test_not_yet_due_task_is_untouched(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sched-future-{suffix}")
    channel, account, version = _fixture(db, project, suffix)
    task = _task(
        db,
        project,
        version,
        channel,
        account,
        suffix,
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db.commit()
    _patch_publisher(monkeypatch)

    stats = run_due_wechat_publishes(db)

    assert stats["due"] == 0
    db.refresh(task)
    assert task.status == PublishTaskStatus.PENDING


def test_manual_task_never_auto_publishes(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sched-manual-{suffix}")
    channel, account, version = _fixture(db, project, suffix)
    task = _task(
        db, project, version, channel, account, suffix, publish_mode=PublishMode.MANUAL
    )
    db.commit()
    _patch_publisher(monkeypatch)

    stats = run_due_wechat_publishes(db)

    assert stats["due"] == 0
    db.refresh(task)
    assert task.status == PublishTaskStatus.PENDING


def test_global_switch_off_skips_everything(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sched-off-{suffix}")
    channel, account, version = _fixture(db, project, suffix)
    task = _task(db, project, version, channel, account, suffix)
    db.commit()
    _patch_publisher(monkeypatch)
    monkeypatch.setattr(settings, "publish_auto_execute_enabled", False)
    _FakePublisher.calls = 0

    stats = run_due_wechat_publishes(db)

    assert stats["enabled"] is False
    assert stats["due"] == 0
    assert _FakePublisher.calls == 0
    db.refresh(task)
    assert task.status == PublishTaskStatus.PENDING


def test_rejected_publish_marks_task_failed_and_continues(db, project_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"sched-reject-{suffix}")
    channel, account, version = _fixture(db, project, suffix)
    task = _task(db, project, version, channel, account, suffix)
    db.commit()
    _patch_publisher(monkeypatch, _RejectedPublisher)

    stats = run_due_wechat_publishes(db)

    assert stats["due"] == 1
    assert stats["failed"] == 1
    db.refresh(task)
    assert task.status == PublishTaskStatus.FAILED
    attempt = db.query(PublishAttempt).filter(PublishAttempt.task_id == task.id).one()
    assert attempt.error_code == "wechat_api_unauthorized"

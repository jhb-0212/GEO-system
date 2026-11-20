"""渠道台账/发布回执一致性异常接口回归。"""

import uuid
from datetime import datetime, timezone

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
    ChannelCategory,
    ChannelStatus,
    ContentKind,
    ContentStatus,
    PublishMode,
    PublishTaskStatus,
    RoleCode,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _make_channel_bundle(db, project, status: ChannelStatus = ChannelStatus.CANDIDATE):
    suffix = uuid.uuid4().hex[:6]
    channel = Channel(
        project_id=project.id,
        code=f"ch-{suffix}",
        name="异常测试渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=status,
        primary_domain="example.com",
    )
    db.add(channel)
    db.flush()

    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"账号-{suffix}",
        is_active=True,
    )
    db.add(account)
    db.flush()

    item = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title="异常测试内容",
        status=ContentStatus.APPROVED,
    )
    db.add(item)
    db.flush()

    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body="异常测试正文",
        content_hash="a" * 64,
        status=ContentStatus.APPROVED,
    )
    db.add(version)
    db.flush()
    return suffix, channel, account, version


def _make_publish_fixture(db, project):
    suffix = uuid.uuid4().hex[:6]
    channel = Channel(
        project_id=project.id,
        code=f"ch-{suffix}",
        name="异常测试渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
        primary_domain="example.com",
    )
    db.add(channel)
    db.flush()

    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"账号-{suffix}",
        is_active=True,
    )
    db.add(account)
    db.flush()

    item = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title="异常测试内容",
        status=ContentStatus.APPROVED,
    )
    db.add(item)
    db.flush()

    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body="异常测试正文",
        content_hash="a" * 64,
        status=ContentStatus.APPROVED,
    )
    db.add(version)
    db.flush()

    published = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"task-published-{suffix}",
        idempotency_key=f"idem-published-{suffix}",
        publish_mode=PublishMode.MANUAL,
        status=PublishTaskStatus.PUBLISHED,
    )
    missing_receipt = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"task-missing-{suffix}",
        idempotency_key=f"idem-missing-{suffix}",
        publish_mode=PublishMode.MANUAL,
        status=PublishTaskStatus.PUBLISHED,
    )
    unknown = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"task-unknown-{suffix}",
        idempotency_key=f"idem-unknown-{suffix}",
        publish_mode=PublishMode.MANUAL,
        status=PublishTaskStatus.UNKNOWN,
    )
    db.add_all([published, missing_receipt, unknown])
    db.flush()

    receipt = PublishReceipt(
        project_id=project.id,
        task_id=published.id,
        published_url="https://example.com/geo-anomaly",
        received_at=datetime(2026, 11, 19, 2, 0, tzinfo=timezone.utc),
    )
    db.add(receipt)
    db.flush()
    return {
        "channel": channel,
        "published": published,
        "missing_receipt": missing_receipt,
        "unknown": unknown,
    }


def test_channel_anomalies_flags_status_and_receipt_mismatches(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"channel-anomaly-{suffix}")
    editor = user_factory(f"channel-anomaly-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    fixture = _make_publish_fixture(db, project)

    response = client.get(
        f"/api/v1/projects/{project.id}/channels/anomalies",
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert data["counts"] == {"total": 3, "high": 2, "warning": 1}
    codes = {row["code"] for row in data["anomalies"]}
    assert codes == {
        "channel_status_mismatch",
        "published_task_missing_receipt",
        "publish_task_unknown",
    }
    mismatch = next(
        row for row in data["anomalies"] if row["code"] == "channel_status_mismatch"
    )
    assert mismatch["channel_code"] == fixture["channel"].code
    assert mismatch["task_status"] == "published"
    assert mismatch["published_url"] == "https://example.com/geo-anomaly"
    assert mismatch["severity"] == "warning"


def test_channel_anomalies_flags_receipt_status_and_duplicate(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"channel-anomaly-receipt-{suffix}")
    editor = user_factory(f"channel-anomaly-receipt-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    bundle_suffix, channel, account, version = _make_channel_bundle(db, project)

    pending = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"task-pending-{bundle_suffix}",
        idempotency_key=f"idem-pending-{bundle_suffix}",
        publish_mode=PublishMode.MANUAL,
        status=PublishTaskStatus.PENDING,
    )
    db.add(pending)
    db.flush()
    for index in (1, 2):
        db.add(
            PublishReceipt(
                project_id=project.id,
                task_id=pending.id,
                published_url=f"https://example.com/duplicate-{index}",
                received_at=datetime(2026, 11, 19, 2, index, tzinfo=timezone.utc),
            )
        )
    db.flush()

    response = client.get(
        f"/api/v1/projects/{project.id}/channels/anomalies",
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["counts"] == {"total": 2, "high": 1, "warning": 1}
    assert {row["code"] for row in data["anomalies"]} == {
        "receipt_status_mismatch",
        "duplicate_receipts",
    }


def test_channel_anomalies_observed_channel_with_published_receipt_is_consistent(
    client, db, project_factory, user_factory, member_factory
):
    """observed 高于 published：已观测渠道回填真实回执后不应再报状态不一致。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"channel-anomaly-observed-{suffix}")
    editor = user_factory(f"channel-anomaly-observed-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    bundle_suffix, channel, account, version = _make_channel_bundle(
        db, project, status=ChannelStatus.OBSERVED
    )

    published = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"task-observed-{bundle_suffix}",
        idempotency_key=f"idem-observed-{bundle_suffix}",
        publish_mode=PublishMode.MANUAL,
        status=PublishTaskStatus.PUBLISHED,
    )
    db.add(published)
    db.flush()
    db.add(
        PublishReceipt(
            project_id=project.id,
            task_id=published.id,
            published_url="https://zhuanlan.zhihu.com/p/2106777058521114619",
            received_at=datetime(2026, 11, 19, 8, 15, tzinfo=timezone.utc),
        )
    )
    db.flush()

    response = client.get(
        f"/api/v1/projects/{project.id}/channels/anomalies",
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["counts"] == {"total": 0, "high": 0, "warning": 0}
    assert data["anomalies"] == []


def test_channel_anomalies_flags_published_channel_without_receipt(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"channel-anomaly-published-{suffix}")
    editor = user_factory(f"channel-anomaly-published-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    bundle_suffix, channel, account, version = _make_channel_bundle(
        db, project, status=ChannelStatus.PUBLISHED
    )

    pending = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"task-pending-{bundle_suffix}",
        idempotency_key=f"idem-pending-{bundle_suffix}",
        publish_mode=PublishMode.MANUAL,
        status=PublishTaskStatus.PENDING,
    )
    db.add(pending)
    db.flush()

    response = client.get(
        f"/api/v1/projects/{project.id}/channels/anomalies",
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["counts"] == {"total": 1, "high": 0, "warning": 1}
    row = data["anomalies"][0]
    assert row["code"] == "published_channel_without_receipt"
    assert row["channel_code"] == channel.code
    assert row["task_id"] is None

"""批次 → 发布任务：把「已投喂」这句话落到可核验的任务上。

钉住五条：
1. 一个批次按「内容版本 × 目标渠道」生成任务，任务带 `source_batch_id`；
2. 批次确认后写入 `approval_snapshot`，冻结渠道准入、发布账号、内容版本与预检哈希；
3. `dispatched` 是终态：重复确认直接拒绝，不改写历史；
4. 渠道没有启用中的发布账号时拒绝确认（错误码 `batch_channel_no_account`），
   不允许出现「批次已投喂但一条任务都没有」；
5. 母稿（master）不能生成发布任务（`batch_content_not_channel`），版本被替代也拒绝
   （`batch_version_replaced`）——与手工建单同口径。
"""

import uuid

import pytest

from app.core.errors import AppError, TaskRejectedError
from app.models import (
    Channel,
    ContentItem,
    ContentVersion,
    DistributionBatch,
    DistributionBatchItem,
    PublishAccount,
    PublishTask,
)
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ContentKind,
    ContentStatus,
    DistributionBatchStatus,
    PublishTaskStatus,
)
from app.services.distribution_dispatch import apply_plan


def _channel(db, project) -> Channel:
    suffix = uuid.uuid4().hex[:6]
    channel = Channel(
        project_id=project.id,
        code=f"dch-{suffix}",
        name=f"渠道-{suffix}",
        category=ChannelCategory.CONTENT_PLATFORM,
        approval_status=ChannelApprovalStatus.APPROVED,
    )
    db.add(channel)
    db.flush()
    return channel


def _account(db, project, channel) -> PublishAccount:
    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"acc-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    db.add(account)
    db.flush()
    return account


def _version(db, project, *, channel=None, kind: ContentKind = ContentKind.CHANNEL, status: ContentStatus = ContentStatus.APPROVED):
    """建一条内容版本。渠道稿必须挂在母稿下并指向渠道（DB 有 check 约束）。"""
    parent_id = None
    if kind == ContentKind.CHANNEL:
        assert channel is not None, "渠道稿必须指定渠道"
        master = ContentItem(
            project_id=project.id, kind=ContentKind.MASTER,
            title=f"母稿-{uuid.uuid4().hex[:6]}", status=status,
        )
        db.add(master)
        db.flush()
        parent_id = master.id
    item = ContentItem(
        project_id=project.id,
        kind=kind,
        title=f"稿-{uuid.uuid4().hex[:6]}",
        status=status,
        parent_id=parent_id,
        channel_id=channel.id if kind == ContentKind.CHANNEL else None,
    )
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body="正文",
        content_hash=uuid.uuid4().hex,
        status=status,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.flush()
    return item, version


def _batch(db, project, *, versions, channels) -> tuple[DistributionBatch, list[DistributionBatchItem]]:
    batch = DistributionBatch(
        project_id=project.id,
        name=f"批次-{uuid.uuid4().hex[:6]}",
        target_channel_ids=[str(channel.id) for channel in channels],
        expected_engines=[],
        item_count=len(versions),
        status=DistributionBatchStatus.READY,
        precheck={"ready": True, "status": "ready", "checks": [], "failed": []},
    )
    db.add(batch)
    db.flush()
    items = []
    for version in versions:
        item = DistributionBatchItem(
            project_id=project.id,
            batch_id=batch.id,
            content_version_id=version.id,
            title="标题",
        )
        db.add(item)
        items.append(item)
    db.flush()
    return batch, items


def test_apply_plan_creates_tasks_and_freezes_snapshot(db, project_factory):
    project = project_factory(f"plan-{uuid.uuid4().hex[:6]}")
    channel_a = _channel(db, project)
    channel_b = _channel(db, project)
    _account(db, project, channel_a)
    _account(db, project, channel_b)
    _, version_one = _version(db, project, channel=channel_a)
    _, version_two = _version(db, project, channel=channel_b)
    batch, items = _batch(db, project, versions=[version_one, version_two], channels=[channel_a, channel_b])
    db.commit()

    plan = apply_plan(
        db, project_id=project.id, batch=batch, items=items, actor_id=None,
        precheck=batch.precheck,
    )
    db.commit()

    assert plan.task_count == 4  # 2 版本 × 2 渠道
    assert len(plan.created) == 4
    assert plan.reused == []
    assert batch.status == DistributionBatchStatus.DISPATCHED
    assert batch.task_count == 4
    assert batch.dispatched_at is not None

    snapshot = batch.approval_snapshot
    assert snapshot["precheck_hash"]
    assert {row["id"] for row in snapshot["channels"]} == {str(channel_a.id), str(channel_b.id)}
    assert len(snapshot["accounts"]) == 2
    assert {row["id"] for row in snapshot["versions"]} == {str(version_one.id), str(version_two.id)}

    tasks = db.query(PublishTask).filter(PublishTask.project_id == project.id).all()
    assert len(tasks) == 4
    assert all(task.source_batch_id == batch.id for task in tasks)
    assert all(task.status == PublishTaskStatus.PENDING for task in tasks)
    assert {task.version_id for task in tasks} == {version_one.id, version_two.id}
    assert {task.channel_id for task in tasks} == {channel_a.id, channel_b.id}
    # 建单即视为待发布
    db.refresh(version_one)
    assert version_one.status == ContentStatus.PENDING_PUBLISH


def test_dispatch_is_terminal_and_idempotent_by_key(db, project_factory):
    project = project_factory(f"plan-term-{uuid.uuid4().hex[:6]}")
    channel = _channel(db, project)
    _account(db, project, channel)
    _, version = _version(db, project, channel=channel)
    batch, items = _batch(db, project, versions=[version], channels=[channel])
    db.commit()

    apply_plan(db, project_id=project.id, batch=batch, items=items, actor_id=None)
    db.commit()
    first_key = db.query(PublishTask).filter(PublishTask.project_id == project.id).one().idempotency_key

    # 终态没有出边：再确认一次直接拒绝
    with pytest.raises(TaskRejectedError):
        apply_plan(db, project_id=project.id, batch=batch, items=items, actor_id=None)
    db.rollback()

    again = db.query(PublishTask).filter(PublishTask.project_id == project.id).all()
    assert len(again) == 1
    assert again[0].idempotency_key == first_key


def test_channel_without_account_refuses_planning(db, project_factory):
    project = project_factory(f"plan-noacc-{uuid.uuid4().hex[:6]}")
    channel = _channel(db, project)
    _, version = _version(db, project, channel=channel)
    batch, items = _batch(db, project, versions=[version], channels=[channel])
    db.commit()

    with pytest.raises(AppError) as exc:
        apply_plan(db, project_id=project.id, batch=batch, items=items, actor_id=None)
    assert exc.value.code == "batch_channel_no_account"
    # 拒绝时不得留下「已投喂但没有任务」的假事实
    assert db.query(PublishTask).filter(PublishTask.project_id == project.id).count() == 0
    db.rollback()
    assert batch.status == DistributionBatchStatus.READY


def test_master_content_and_replaced_version_refused(db, project_factory):
    project = project_factory(f"plan-kind-{uuid.uuid4().hex[:6]}")
    channel = _channel(db, project)
    _account(db, project, channel)

    _, master = _version(db, project, kind=ContentKind.MASTER)
    batch, items = _batch(db, project, versions=[master], channels=[channel])
    db.commit()
    with pytest.raises(AppError) as exc:
        apply_plan(db, project_id=project.id, batch=batch, items=items, actor_id=None)
    assert exc.value.code == "batch_content_not_channel"
    db.rollback()

    item, old_version = _version(db, project, channel=channel)
    replacement = ContentVersion(
        project_id=project.id, item_id=item.id, version_no=2,
        body="新正文", content_hash=uuid.uuid4().hex, status=ContentStatus.APPROVED,
    )
    db.add(replacement)
    db.flush()
    item.current_version_id = replacement.id  # 旧版本被替代
    db.flush()
    batch, items = _batch(db, project, versions=[old_version], channels=[channel])
    db.commit()
    with pytest.raises(AppError) as exc:
        apply_plan(db, project_id=project.id, batch=batch, items=items, actor_id=None)
    assert exc.value.code == "batch_version_replaced"


def test_dispatch_requires_publish_execute_permission(client, db, project_factory, user_factory, member_factory):
    """审核岗（没有 publish.execute）不能代替执行岗确认投喂。"""
    from app.core.security import create_access_token
    from app.models.enums import RoleCode

    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"plan-perm-{suffix}")
    reviewer = user_factory(f"plan-rev-{suffix}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel = _channel(db, project)
    _, version = _version(db, project, channel=channel)
    batch, _ = _batch(db, project, versions=[version], channels=[channel])
    db.commit()

    response = client.post(
        f"/api/v1/projects/{project.id}/distribution-batches/{batch.id}/dispatch",
        headers={"Authorization": f"Bearer {create_access_token(reviewer.id, token_version=reviewer.token_version)}"},
    )
    assert response.status_code == 403, response.text

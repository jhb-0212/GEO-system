"""发布闭环：按任务判定断点阶段，失败任务与未发布任务分开计。"""

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
    PublishVisibilityCheck,
)
from app.models.enums import (
    ChannelCategory,
    ContentKind,
    ContentStatus,
    PublishMode,
    PublishTaskStatus,
    RoleCode,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_closure_stages(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"closure-{suffix}")
    editor = user_factory(f"closure-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    channel = Channel(project_id=project.id, code=f"c-{suffix}", name="闭环渠道", category=ChannelCategory.CONTENT_PLATFORM)
    db.add(channel)
    db.flush()

    account = PublishAccount(project_id=project.id, channel_id=channel.id, account_name="闭环账号")
    db.add(account)
    db.flush()

    def make_task(serial: int, status: PublishTaskStatus) -> PublishTask:
        item = ContentItem(project_id=project.id, kind=ContentKind.MASTER, title=f"稿-{suffix}-{serial}", status=ContentStatus.APPROVED)
        db.add(item)
        db.flush()
        version = ContentVersion(
            project_id=project.id, item_id=item.id, version_no=1, body="正文",
            content_hash=uuid.uuid4().hex, status=ContentStatus.APPROVED,
        )
        db.add(version)
        db.flush()
        task = PublishTask(
            project_id=project.id, version_id=version.id, channel_id=channel.id,
            account_id=account.id, task_key=f"key-{suffix}-{serial}", idempotency_key=f"idem-{suffix}-{serial}",
            publish_mode=PublishMode.MANUAL, status=status,
        )
        db.add(task)
        db.flush()
        return task

    # 1) 未发布任务、2) 失败任务、3) 有回执未检测、4) 已检测未收录、5) 已收录未引用、6) 闭环
    pending = make_task(1, PublishTaskStatus.PENDING)
    failed = make_task(2, PublishTaskStatus.FAILED)
    unchecked = make_task(3, PublishTaskStatus.PUBLISHED)

    receipt_3 = PublishReceipt(project_id=project.id, task_id=unchecked.id, published_url="https://a.example.com/x3", received_at=datetime.now(timezone.utc))
    db.add(receipt_3)

    not_indexed = make_task(4, PublishTaskStatus.PUBLISHED)
    receipt_4 = PublishReceipt(project_id=project.id, task_id=not_indexed.id, published_url="https://b.example.com/x4", received_at=datetime.now(timezone.utc))
    db.add(receipt_4)
    db.flush()
    db.add(PublishVisibilityCheck(project_id=project.id, receipt_id=receipt_4.id, checked_at=datetime.now(timezone.utc), matched=False, query="q4"))

    not_cited = make_task(5, PublishTaskStatus.PUBLISHED)
    receipt_5 = PublishReceipt(project_id=project.id, task_id=not_cited.id, published_url="https://c.example.com/x5", received_at=datetime.now(timezone.utc))
    db.add(receipt_5)
    db.flush()
    db.add(PublishVisibilityCheck(project_id=project.id, receipt_id=receipt_5.id, checked_at=datetime.now(timezone.utc), matched=True, query="q5"))

    closed = make_task(6, PublishTaskStatus.PUBLISHED)
    receipt_6 = PublishReceipt(project_id=project.id, task_id=closed.id, published_url="https://d.example.com/x6", received_at=datetime.now(timezone.utc))
    db.add(receipt_6)
    db.flush()
    db.add(PublishVisibilityCheck(project_id=project.id, receipt_id=receipt_6.id, checked_at=datetime.now(timezone.utc), matched=True, query="q6"))

    data = client.get(f"/api/v1/projects/{project.id}/publish-closure", headers=_auth(editor)).json()["data"]
    stages = {item["task_id"]: item["stage"] for item in data["items"]}
    assert stages[str(pending.id)] == "not_published"
    assert stages[str(failed.id)] == "task_closed"
    assert stages[str(unchecked.id)] == "not_checked"
    assert stages[str(not_indexed.id)] == "not_in_index"
    assert stages[str(not_cited.id)] == "not_cited"
    # 没有人工复核引用时，即使已收录也只到「未被引用」——引用判定不靠猜测
    assert stages[str(closed.id)] == "not_cited"

    assert data["summary"]["closed"] == 0
    assert data["summary"]["tasks_with_receipt"] == 4
    assert data["summary"]["closure_rate"] == 0.0
    assert data["summary"]["broken_before_receipt"] == 1
    assert data["summary"]["broken_after_receipt"] == 4


def test_stage_function_covers_all_branches():
    """链路断点判定逐条覆盖：检测失败不并入未收录、取消不算缺回执。"""
    from app.models.enums import PublishTaskStatus
    from app.services.publish_closure import stage_of

    assert stage_of(PublishTaskStatus.PENDING, False, None, False) == "not_published"
    assert stage_of(PublishTaskStatus.FAILED, False, None, False) == "task_closed"
    assert stage_of(PublishTaskStatus.CANCELLED, False, None, False) == "task_closed"
    assert stage_of(PublishTaskStatus.PUBLISHED, False, None, False) == "no_receipt"
    assert stage_of(PublishTaskStatus.PUBLISHED, True, None, False) == "not_checked"
    assert stage_of(PublishTaskStatus.PUBLISHED, True, {"matched": False, "error_code": "timeout"}, False) == "check_failed"
    assert stage_of(PublishTaskStatus.PUBLISHED, True, {"matched": False, "error_code": None}, False) == "not_in_index"
    assert stage_of(PublishTaskStatus.PUBLISHED, True, {"matched": True, "error_code": None}, False) == "not_cited"
    assert stage_of(PublishTaskStatus.PUBLISHED, True, {"matched": True, "error_code": None}, True) == "closed"


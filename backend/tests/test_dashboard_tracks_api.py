"""B1 双轨大屏：两列分开算，不合成总分。

钉住四条：
1. 两侧 track 都在、标签正确，且不出现任何「合并总分」字段；
2. 取消的发布任务不进退款/回执比率的分母，但仍计入累计；
3. 无数据时比率为 None，不拿 0 冒充；
4. 闭环必须「回执 + 收录命中」同时具备。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

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


def _project_and_member(project_factory, user_factory, member_factory, role=RoleCode.EDITOR):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"dash-{suffix}")
    user = user_factory(f"dash-u-{suffix}")
    member_factory(project, user, role)
    return project, user


def _tracks(client, project, user, days: int = 30) -> dict:
    resp = client.get(
        f"/api/v1/projects/{project.id}/dashboard/tracks?days={days}", headers=_auth(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _metric(track: dict, key: str) -> dict:
    return next(item for item in track["metrics"] if item["key"] == key)


def _channel_and_account(db, project):
    suffix = uuid.uuid4().hex[:6]
    channel = Channel(
        project_id=project.id,
        code=f"dash-{suffix}",
        name="大屏渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
    )
    db.add(channel)
    db.flush()
    account = PublishAccount(project_id=project.id, channel_id=channel.id, account_name="大屏账号")
    db.add(account)
    db.flush()
    return channel, account


def _make_task(db, project, channel, account, status: PublishTaskStatus) -> PublishTask:
    suffix = uuid.uuid4().hex[:6]
    item = ContentItem(
        project_id=project.id, kind=ContentKind.MASTER, title=f"大屏稿-{suffix}",
        status=ContentStatus.APPROVED,
    )
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id, item_id=item.id, version_no=1, body="正文",
        content_hash=uuid.uuid4().hex, status=ContentStatus.APPROVED,
    )
    db.add(version)
    db.flush()
    task = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"key-{suffix}",
        idempotency_key=f"idem-{suffix}",
        publish_mode=PublishMode.MANUAL,
        status=status,
        created_at=datetime.now(UTC),
    )
    db.add(task)
    db.flush()
    return task


def test_empty_project_returns_null_rates(client, db, project_factory, user_factory, member_factory):
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    data = _tracks(client, project, user)
    assert [track["track"] for track in data["tracks"]] == ["dispatch", "measurement"]
    assert [track["label"] for track in data["tracks"]] == ["投放侧", "测量侧"]
    for track in data["tracks"]:
        for metric in track["metrics"]:
            if metric["denominator"] == 0 and metric["unit"] == "%":
                assert metric["value"] is None
                assert metric["has_data"] is False
    assert "total" not in data and "score" not in data


def test_cancelled_task_excluded_from_denominator(
    client, db, project_factory, user_factory, member_factory
):
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    channel, account = _channel_and_account(db, project)
    _make_task(db, project, channel, account, PublishTaskStatus.PUBLISHED)
    _make_task(db, project, channel, account, PublishTaskStatus.CANCELLED)
    db.commit()

    dispatch = _tracks(client, project, user)["tracks"][0]
    assert _metric(dispatch, "tasks_total")["numerator"] == 2
    # 分母只剩 1（未取消）；若把取消的也计入分母会变成 50%
    assert _metric(dispatch, "published")["denominator"] == 1
    assert _metric(dispatch, "published")["value"] == 1.0


def test_closure_requires_receipt_and_indexed_check(
    client, db, project_factory, user_factory, member_factory
):
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    channel, account = _channel_and_account(db, project)
    task = _make_task(db, project, channel, account, PublishTaskStatus.PUBLISHED)
    db.add(
        PublishReceipt(
            project_id=project.id,
            task_id=task.id,
            published_url="https://example.com/a",
            received_at=datetime.now(UTC),
        )
    )
    db.commit()

    dispatch = _tracks(client, project, user)["tracks"][0]
    # 只有回执没有收录检测：闭环必须是 0，不能因为「有回执」就算通
    assert _metric(dispatch, "receipts")["numerator"] == 1
    assert _metric(dispatch, "closure")["numerator"] == 0
    assert _metric(dispatch, "closure")["value"] == 0.0

    # 补一条命中的收录检测后闭环才算 1
    receipt = db.scalar(select(PublishReceipt).where(PublishReceipt.task_id == task.id))
    db.add(
        PublishVisibilityCheck(
            project_id=project.id,
            receipt_id=receipt.id,
            checked_at=datetime.now(UTC),
            matched=True,
            query="广州 AI 实训基地",
        )
    )
    db.commit()
    after = _tracks(client, project, user)["tracks"][0]
    assert _metric(after, "indexed")["numerator"] == 1
    assert _metric(after, "closure")["numerator"] == 1


def test_measurement_track_counts_valid_samples(
    client, db, project_factory, user_factory, member_factory
):
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    measurement = _tracks(client, project, user)["tracks"][1]
    assert _metric(measurement, "samples_total")["numerator"] == 0
    assert _metric(measurement, "mentioned")["value"] is None
    assert measurement["notes"]

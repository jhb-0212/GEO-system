"""回执三态之一「可访问」：判定表与失败不改结论。

钉住四条：
1. 2xx/3xx/401/403/429 判为可访问；404/410 判为不可访问；其余无法判定；
2. 网络失败只写 error，不清空历史结论；
3. 单条失败不影响整批；
4. 发布看板带出 reachable 字段与统计。
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
)
from app.models.enums import (
    ChannelCategory,
    ContentKind,
    ContentStatus,
    PublishMode,
    PublishTaskStatus,
    RoleCode,
)
from app.services import reachability
from app.services.reachability import judge


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_judge_table():
    assert judge(200, None) is True
    assert judge(301, None) is True
    assert judge(403, None) is True
    assert judge(429, None) is True
    assert judge(404, None) is False
    assert judge(410, None) is False
    assert judge(400, None) is None
    assert judge(500, None) is None
    assert judge(None, "timeout") is None


def _seed_receipts(db, project, urls: list[str]) -> list[PublishReceipt]:
    suffix = uuid.uuid4().hex[:6]
    channel = Channel(project_id=project.id, code=f"r-{suffix}", name="回抓渠道", category=ChannelCategory.CONTENT_PLATFORM)
    db.add(channel)
    db.flush()
    account = PublishAccount(project_id=project.id, channel_id=channel.id, account_name="回抓账号")
    db.add(account)
    db.flush()
    receipts = []
    for index, url in enumerate(urls):
        item = ContentItem(project_id=project.id, kind=ContentKind.MASTER, title=f"回抓稿-{index}", status=ContentStatus.APPROVED)
        db.add(item)
        db.flush()
        version = ContentVersion(
            project_id=project.id, item_id=item.id, version_no=1, body="正文",
            content_hash=uuid.uuid4().hex, status=ContentStatus.APPROVED,
        )
        db.add(version)
        db.flush()
        task = PublishTask(
            project_id=project.id, version_id=version.id, channel_id=channel.id, account_id=account.id,
            task_key=f"key-{suffix}-{index}", idempotency_key=f"idem-{suffix}-{index}",
            publish_mode=PublishMode.MANUAL, status=PublishTaskStatus.PUBLISHED,
        )
        db.add(task)
        db.flush()
        receipt = PublishReceipt(
            project_id=project.id, task_id=task.id, published_url=url,
            received_at=datetime.now(UTC),
        )
        db.add(receipt)
        receipts.append(receipt)
    db.flush()
    return receipts


def test_reachability_batch_keeps_history_on_failure(client, db, project_factory, user_factory, member_factory, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"reach-{suffix}")
    editor = user_factory(f"reach-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    receipts = _seed_receipts(db, project, [
        "https://a.example.com/ok", "https://b.example.com/gone", "https://c.example.com/timeout",
    ])
    # 先给其中一条一个历史结论，验证网络失败不覆盖它
    receipts[2].last_reachable = True
    db.commit()

    def fake_fetch(url: str):
        if "ok" in url:
            return 200, None
        if "gone" in url:
            return 404, None
        return None, "timeout"

    monkeypatch.setattr(reachability, "_default_fetch", fake_fetch)

    response = client.post(
        f"/api/v1/projects/{project.id}/stats/publish-receipts/reachability-check?limit=10",
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text
    summary = response.json()["data"]
    assert summary["checked"] == 3
    assert summary["reachable"] == 1
    assert summary["unreachable"] == 1
    assert summary["failed"] == 1

    db.expire_all()
    rows = {row.published_url: row for row in db.scalars(
        select(PublishReceipt).where(PublishReceipt.project_id == project.id)
    ).all()}
    assert rows["https://a.example.com/ok"].last_reachable is True
    assert rows["https://b.example.com/gone"].last_reachable is False
    # 超时那条保留历史 True，只记 error
    assert rows["https://c.example.com/timeout"].last_reachable is True
    assert rows["https://c.example.com/timeout"].last_reachability_error == "timeout"


def test_board_exposes_three_states(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"board3-{suffix}")
    editor = user_factory(f"board3-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    receipts = _seed_receipts(db, project, ["https://d.example.com/p1"])
    receipts[0].last_reachable = True
    receipts[0].last_reachability_status = 200
    receipts[0].last_reachability_at = datetime.now(UTC)
    db.commit()

    response = client.get(f"/api/v1/projects/{project.id}/publish-board", headers=_auth(editor))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    item = data["items"][0]
    assert item["reachable"] is True
    assert item["reachability_status"] == 200
    assert item["reachability_checked_at"] is not None
    assert data["summary"]["reachability_checked"] == 1
    assert data["summary"]["reachable"] == 1
    assert data["summary"]["reachable_rate"] == 1.0
    assert any("可访问" in caveat for caveat in data["caveats"])

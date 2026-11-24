"""渠道改编：只有过审母稿能派生、渠道约束检查、母稿改动后判定未跟版、跟版后回 draft。"""

import uuid

from app.core.security import create_access_token
from app.models import Channel, ContentItem, ContentVersion
from app.models.enums import ChannelCategory, ContentKind, ContentStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _master(db, project, status: ContentStatus, body: str) -> tuple[ContentItem, ContentVersion]:
    suffix = uuid.uuid4().hex[:6]
    item = ContentItem(project_id=project.id, kind=ContentKind.MASTER, title=f"母稿-{suffix}", status=status)
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id, item_id=item.id, version_no=1, body=body,
        content_hash=uuid.uuid4().hex, status=status,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.flush()
    return item, version


def _channel(db, project, category: ChannelCategory) -> Channel:
    suffix = uuid.uuid4().hex[:6]
    channel = Channel(project_id=project.id, code=f"ch-{suffix}", name=f"渠道-{suffix}", category=category)
    db.add(channel)
    db.flush()
    return channel


def test_derive_requires_approval_and_checks(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"derive-{suffix}")
    editor = user_factory(f"derive-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}/contents"

    # 未过审母稿不能改编
    draft_item, _ = _master(db, project, ContentStatus.DRAFT, "草稿正文")
    blocked = client.post(f"{base}/{draft_item.id}/derive", json={"channel_ids": [str(uuid.uuid4())]}, headers=_auth(editor))
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "master_version_not_approved"

    body = "广东省AI数字人才就业实训基地 番禺校区 小班实训 www.example.com"
    master, version = _master(db, project, ContentStatus.APPROVED, body)
    zhihu = _channel(db, project, ChannelCategory.CONTENT_PLATFORM)
    wiki = _channel(db, project, ChannelCategory.ENCYCLOPEDIA)

    created = client.post(
        f"{base}/{master.id}/derive",
        json={"channel_ids": [str(zhihu.id), str(wiki.id)]},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert len(data["created"]) == 2
    rows = {row["channel_name"]: row for row in data["created"]}

    # 百科：外链被判不通过；内容平台：外链允许
    wiki_row = rows[wiki.name]
    zhihu_row = rows[zhihu.name]
    wiki_link = next(check for check in wiki_row["checks"] if check["key"] == "external_link")
    zhihu_link = next(check for check in zhihu_row["checks"] if check["key"] == "external_link")
    assert wiki_link["ok"] is False
    assert zhihu_link["ok"] is True
    assert wiki_row["version_status"] == "draft"

    # 渠道稿是 kind=channel 且挂到母稿与渠道上
    channel_item = db.get(ContentItem, uuid.UUID(zhihu_row["channel_item_id"]))
    assert channel_item.kind == ContentKind.CHANNEL
    assert channel_item.parent_id == master.id
    assert channel_item.channel_id == zhihu.id

    # 同一渠道重复改编被拒
    again = client.post(f"{base}/{master.id}/derive", json={"channel_ids": [str(zhihu.id)]}, headers=_auth(editor))
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "derivation_exists"

    # 母稿换版后：列出血缘里标为未跟版
    new_version = ContentVersion(
        project_id=project.id, item_id=master.id, version_no=2, body="改过的正文",
        content_hash="f" * 64, status=ContentStatus.APPROVED,
    )
    db.add(new_version)
    db.flush()
    master.current_version_id = new_version.id
    db.commit()

    listed = client.get(f"{base}/{master.id}/derivations", headers=_auth(editor))
    assert listed.status_code == 200
    assert listed.json()["data"]["stale_count"] == 2

    # 跟版：渠道稿出新版本、回到 draft、来源哈希同步
    sync_id = zhihu_row["id"]
    synced = client.post(f"{base}/{master.id}/derivations/{sync_id}/sync", headers=_auth(editor))
    assert synced.status_code == 200, synced.text
    payload = synced.json()["data"]
    assert payload["stale"] is False
    assert payload["version_status"] == "draft"
    channel_item_after = db.get(ContentItem, uuid.UUID(zhihu_row["channel_item_id"]))
    synced_version = db.get(ContentVersion, channel_item_after.current_version_id)
    assert synced_version.version_no == 2

    # 项目级一致性清单：只剩未跟版的那一条（百科）
    consistency = client.get(f"/api/v1/projects/{project.id}/contents/derivations?stale_only=true", headers=_auth(editor))
    assert consistency.status_code == 200
    assert consistency.json()["meta"]["total"] == 1


def test_consistency_list_paginates_in_database(
    client, db, project_factory, user_factory, member_factory
):
    """一致性清单的 total 是全项目条数，不是「当前页条数」——分页必须在数据库侧完成。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"derive-page-{suffix}")
    editor = user_factory(f"derive-page-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}/contents"

    master, _ = _master(db, project, ContentStatus.APPROVED, "母稿正文")
    channels = [_channel(db, project, ChannelCategory.CONTENT_PLATFORM) for _ in range(3)]
    derived = client.post(
        f"{base}/{master.id}/derive",
        json={"channel_ids": [str(channel.id) for channel in channels]},
        headers=_auth(editor),
    )
    assert derived.status_code == 201, derived.text
    assert len(derived.json()["data"]["created"]) == 3

    first = client.get(f"{base}/derivations?page=1&page_size=2", headers=_auth(editor))
    assert first.status_code == 200
    body = first.json()
    assert len(body["data"]) == 2
    assert body["meta"]["total"] == 3

    second = client.get(f"{base}/derivations?page=2&page_size=2", headers=_auth(editor))
    assert len(second.json()["data"]) == 1
    assert second.json()["meta"]["total"] == 3
    # 两页不重复
    ids = {row["id"] for row in body["data"]} | {row["id"] for row in second.json()["data"]}
    assert len(ids) == 3

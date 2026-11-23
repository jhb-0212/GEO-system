"""投喂批次：目标只能是渠道，期望引擎不阻断。

钉住五条：
1. 空批次与无渠道批次直接拒绝（错误码改成 batch_no_channel）；
2. 预检六项：企业档案 / 品牌 / 内容 / 目标渠道 / FAQ / 期望引擎；
3. 未准入渠道（pending_review）不通过预检——这是「未准入不能发」在投喂侧的落点；
4. 期望引擎即使写错 id 也只提示、不阻断；
5. 预检未过不得标记已投喂。
"""

import uuid

from app.core.security import create_access_token
from app.models import AiEngine, Channel, ContentItem, ContentVersion
from app.models.enums import ChannelApprovalStatus, ChannelCategory, ContentKind, ContentStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _approved_version(db, project) -> ContentVersion:
    suffix = uuid.uuid4().hex[:6]
    item = ContentItem(project_id=project.id, kind=ContentKind.MASTER, title=f"稿-{suffix}", status=ContentStatus.APPROVED)
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id, item_id=item.id, version_no=1,
        body="正文", content_hash=uuid.uuid4().hex, status=ContentStatus.APPROVED,
    )
    db.add(version)
    db.flush()
    return version


def _channel(db, project, *, approval: ChannelApprovalStatus = ChannelApprovalStatus.APPROVED) -> Channel:
    suffix = uuid.uuid4().hex[:6]
    channel = Channel(
        project_id=project.id, code=f"ch-{suffix}", name=f"渠道-{suffix}",
        category=ChannelCategory.CONTENT_PLATFORM, approval_status=approval,
    )
    db.add(channel)
    db.flush()
    return channel


def _engine(db) -> AiEngine:
    engine = AiEngine(code=f"eng-{uuid.uuid4().hex[:6]}", name="引擎", vendor="测试", supports_search=True, is_active=True)
    db.add(engine)
    db.flush()
    return engine


def test_batch_precheck_and_dispatch_guard(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"dist-{suffix}")
    editor = user_factory(f"dist-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    version = _approved_version(db, project)
    channel = _channel(db, project)
    engine = _engine(db)
    db.commit()
    base = f"/api/v1/projects/{project.id}/distribution-batches"

    assert client.post(base, json={"name": "空批次"}, headers=_auth(editor)).json()["error"]["code"] == "batch_empty"
    assert client.post(base, json={"name": "无渠道", "content_version_ids": [str(version.id)]}, headers=_auth(editor)).json()["error"]["code"] == "batch_no_channel"

    created = client.post(
        base,
        json={
            "name": "首批投喂",
            "content_version_ids": [str(version.id)],
            "channel_ids": [str(channel.id)],
            "expected_engine_ids": [str(engine.id)],
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["channel_names"] == [channel.name]
    assert data["expected_engine_names"] == [engine.name]
    keys = [item["key"] for item in data["precheck"]["checks"]]
    assert keys == [
        "company_profile", "brand_profile", "content_approved", "target_channels", "faq_approved", "expected_engines",
    ]
    assert data["status"] == "blocked"
    assert set(data["precheck"]["failed"]) >= {"company_profile", "brand_profile", "faq_approved"}
    checks = {item["key"]: item for item in data["precheck"]["checks"]}
    assert checks["content_approved"]["ok"] is True
    assert checks["target_channels"]["ok"] is True
    assert checks["expected_engines"]["ok"] is True

    dispatch = client.post(f"{base}/{data['id']}/dispatch", headers=_auth(editor))
    assert dispatch.status_code == 400
    assert dispatch.json()["error"]["code"] == "batch_precheck_failed"

    rechecked = client.post(f"{base}/{data['id']}/recheck", headers=_auth(editor))
    assert rechecked.status_code == 200
    assert rechecked.json()["data"]["status"] == "blocked"

    listed = client.get(base, headers=_auth(editor))
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1
    assert listed.json()["data"][0]["item_count"] == 1


def test_pending_channel_blocks_precheck(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"dist-pending-{suffix}")
    editor = user_factory(f"dist-pending-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    version = _approved_version(db, project)
    pending_channel = _channel(db, project, approval=ChannelApprovalStatus.PENDING_REVIEW)
    db.commit()
    base = f"/api/v1/projects/{project.id}/distribution-batches"

    created = client.post(
        base,
        json={"name": "未准入渠道", "content_version_ids": [str(version.id)], "channel_ids": [str(pending_channel.id)]},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    checks = {item["key"]: item for item in created.json()["data"]["precheck"]["checks"]}
    assert checks["target_channels"]["ok"] is False
    assert "target_channels" in created.json()["data"]["precheck"]["failed"]


def test_expected_engine_typo_does_not_block(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"dist-eng-{suffix}")
    editor = user_factory(f"dist-eng-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    version = _approved_version(db, project)
    channel = _channel(db, project)
    db.commit()
    base = f"/api/v1/projects/{project.id}/distribution-batches"

    created = client.post(
        base,
        json={
            "name": "期望引擎写错",
            "content_version_ids": [str(version.id)],
            "channel_ids": [str(channel.id)],
            "expected_engine_ids": ["not-a-uuid"],
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    checks = {item["key"]: item for item in created.json()["data"]["precheck"]["checks"]}
    # 引擎是结果不是目标：写错只提示，不进 failed
    assert checks["expected_engines"]["ok"] is True
    assert "已忽略该期望" in checks["expected_engines"]["detail"]

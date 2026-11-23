"""投喂批次：预检五项、空批次拒绝、预检未过不得标记已投喂。"""

import uuid

from app.core.security import create_access_token
from app.models import AiEngine, ContentItem, ContentVersion
from app.models.enums import ContentKind, ContentStatus, RoleCode


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
    engine = _engine(db)
    db.commit()
    base = f"/api/v1/projects/{project.id}/distribution-batches"

    # 空批次直接拒绝，不落库
    assert client.post(base, json={"name": "空批次"}, headers=_auth(editor)).json()["error"]["code"] == "batch_empty"
    assert client.post(base, json={"name": "无平台", "content_version_ids": [str(version.id)]}, headers=_auth(editor)).json()["error"]["code"] == "batch_no_engine"

    created = client.post(
        base,
        json={"name": "首批投喂", "content_version_ids": [str(version.id)], "engine_ids": [str(engine.id)]},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    keys = [item["key"] for item in data["precheck"]["checks"]]
    assert keys == ["company_profile", "brand_profile", "content_approved", "target_engines", "faq_approved"]
    # 新项目没有企业档案/品牌/FAQ → 必须 blocked
    assert data["status"] == "blocked"
    assert set(data["precheck"]["failed"]) >= {"company_profile", "brand_profile", "faq_approved"}
    # 内容版本与平台这两项通过
    checks = {item["key"]: item for item in data["precheck"]["checks"]}
    assert checks["content_approved"]["ok"] is True
    assert checks["target_engines"]["ok"] is True

    # 预检没过不许标记已投喂
    dispatch = client.post(f"{base}/{data['id']}/dispatch", headers=_auth(editor))
    assert dispatch.status_code == 400
    assert dispatch.json()["error"]["code"] == "batch_precheck_failed"

    # 重检结论一致，仍 blocked
    rechecked = client.post(f"{base}/{data['id']}/recheck", headers=_auth(editor))
    assert rechecked.status_code == 200
    assert rechecked.json()["data"]["status"] == "blocked"

    listed = client.get(base, headers=_auth(editor))
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1
    assert listed.json()["data"][0]["item_count"] == 1

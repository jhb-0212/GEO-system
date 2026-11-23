"""内容工厂模板：槽位解析、缺槽拒绝、生成草稿与停用后不可生成。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import ContentItem
from app.models.enums import ContentStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_template_slot_parsing_and_generate(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"tpl-{suffix}")
    editor = user_factory(f"tpl-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}/content-templates"

    # 没有槽位的骨架被拒
    no_slot = client.post(base, json={"name": "无槽位", "skeleton": "固定正文"}, headers=_auth(editor))
    assert no_slot.status_code == 400
    assert no_slot.json()["error"]["code"] == "template_no_slot"

    created = client.post(
        base,
        json={
            "name": "小红书种草",
            "channel_category": "content_platform",
            "question_type": "general",
            "skeleton": "【{{品牌}}】{{卖点}}\n校区：{{地址}}",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    # {{品牌}} / {{卖点}} / {{地址}} 全部解析为必填槽位，按出现顺序
    assert [slot["key"] for slot in data["slots"]] == ["品牌", "卖点", "地址"]
    assert all(slot["required"] for slot in data["slots"])

    # 缺槽直接 400，且报出缺哪几个
    missing = client.post(
        f"{base}/{data['id']}/generate",
        json={"title": "草稿-缺槽", "slot_values": {"品牌": "成才"}},
        headers=_auth(editor),
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "template_slot_missing"
    assert "卖点" in missing.json()["error"]["message"]

    generated = client.post(
        f"{base}/{data['id']}/generate",
        json={"title": "番禺校区种草稿", "slot_values": {"品牌": "成才", "卖点": "小班实训", "地址": "番禺番山创业中心"}},
        headers=_auth(editor),
    )
    assert generated.status_code == 201, generated.text
    result = generated.json()["data"]
    assert result["body"].startswith("【成才】小班实训")
    assert "番禺番山创业中心" in result["body"]
    assert result["status"] == "draft"

    # 生成的是普通草稿内容，落了 ContentItem 与当前版本
    item = db.scalar(
        select(ContentItem).where(ContentItem.id == uuid.UUID(result["item_id"]))
    )
    assert item is not None
    assert item.status == ContentStatus.DRAFT

    # 同槽位重复出现只算一个
    dup = client.post(base, json={"name": "重复槽位", "skeleton": "{{品牌}} 与 {{品牌}}"}, headers=_auth(editor))
    assert [slot["key"] for slot in dup.json()["data"]["slots"]] == ["品牌"]

    # 停用后不能生成
    client.patch(f"{base}/{data['id']}", json={"is_active": False}, headers=_auth(editor))
    blocked = client.post(
        f"{base}/{data['id']}/generate",
        json={"title": "停用模板", "slot_values": {"品牌": "x", "卖点": "y", "地址": "z"}},
        headers=_auth(editor),
    )
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "template_inactive"

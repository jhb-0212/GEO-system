"""拒绝模块「替代做法」的收尾四项：批次视图、口径字典、留言固定话术、哈希盐轮换。"""

import importlib.util
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.security import create_access_token
from app.models import DistributionBatch, Lead, ProjectContact
from app.models.enums import DistributionBatchStatus, RoleCode
from app.services import lead_autoreply
from app.services.lead_visitors import hash_visitor


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_publish_board_batches_flags_not_dispatched(
    client, db, project_factory, user_factory, member_factory
):
    """没确认投喂的批次必须出现在视图里并标 not_dispatched，而不是悄悄消失。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"batches-{suffix}")
    editor = user_factory(f"batches-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    batch = DistributionBatch(
        project_id=project.id,
        name="第一批投喂",
        status=DistributionBatchStatus.READY,
        target_channel_ids=[],
        expected_engines=[],
        task_count=0,
        item_count=2,
    )
    db.add(batch)
    db.commit()

    resp = client.get(f"/api/v1/projects/{project.id}/publish-board/batches", headers=_auth(editor))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["summary"]["batches"] == 1
    assert data["summary"]["not_dispatched"] == 1
    item = data["items"][0]
    assert item["stage"] == "not_dispatched"
    assert item["tasks_total"] == 0
    # 没有任务时回执率是 null，不用 0 假装「发了没人给回执」
    assert item["receipt_rate"] is None
    assert any("手工建单" in note for note in data["caveats"])


def test_lead_autoreply_is_off_by_default_and_replies_once(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"autoreply-{suffix}")
    editor = user_factory(f"autoreply-editor-{suffix}")
    # 留言读写属于 lead.* 能力，归招生/客服角色
    member_factory(project, editor, RoleCode.LEAD_OPS)
    base = f"/api/v1/projects/{project.id}/leads"

    policy = client.get(f"{base}/autoreply", headers=_auth(editor)).json()["data"]
    assert policy["enabled"] is False
    # 默认话术不含数字承诺以外的自由文本，且明确写着不调用模型
    assert "不调用模型" in policy["note"]

    lead = Lead(project_id=project.id, lead_source="官网")
    db.add(lead)
    db.commit()

    first = client.post(
        f"{base}/{lead.id}/messages",
        json={"author_role": "visitor", "body": "你们怎么收费？"},
        headers=_auth(editor),
    )
    assert first.status_code == 201, first.text
    # 开关关着：只落访客留言，不多发一句
    assert first.json()["data"]["auto_reply"] is None

    saved = client.put(
        f"{base}/autoreply",
        json={"enabled": True, "script": "已收到，我们会在工作时间由人工回复。", "include_contact": True},
        headers=_auth(editor),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["enabled"] is True

    second = client.post(
        f"{base}/{lead.id}/messages",
        json={"author_role": "visitor", "body": "在吗"},
        headers=_auth(editor),
    ).json()["data"]
    reply = second["auto_reply"]
    assert reply is not None
    assert reply["author_role"] == "auto"
    assert "工作时间" in reply["body"]

    # 同一条线索只回一次，第二条访客留言不再触发
    third = client.post(
        f"{base}/{lead.id}/messages",
        json={"author_role": "visitor", "body": "还在吗"},
        headers=_auth(editor),
    ).json()["data"]
    assert third["auto_reply"] is None

    # 运营自己的留言不触发自问自答
    operator_raw = client.post(
        f"{base}/{lead.id}/messages",
        json={"author_role": "staff", "body": "已安排同事联系您"},
        headers=_auth(editor),
    )
    assert operator_raw.status_code == 201, operator_raw.text
    operator = operator_raw.json()["data"]
    assert operator["auto_reply"] is None


def test_autoreply_contact_line_only_uses_public_contacts(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"autoreply2-{suffix}")
    editor = user_factory(f"autoreply2-editor-{suffix}")
    member_factory(project, editor, RoleCode.LEAD_OPS)

    db.add(
        ProjectContact(
            project_id=project.id,
            channel="phone",
            value="13800000000",
            label="招生电话",
            is_public=True,
            is_active=True,
            sort_order=0,
        )
    )
    db.add(
        ProjectContact(
            project_id=project.id,
            channel="phone",
            value="13900000000",
            label="内部对接",
            is_public=False,
            is_active=True,
            sort_order=-1,
        )
    )
    db.commit()

    body = lead_autoreply.compose(db, project.id)
    # 内部对接号不外露，即便排序更靠前
    assert "13900000000" not in body
    if "13800000000" in body:
        assert "招生电话" in body


def test_visitor_hash_rotates_with_salt_and_version(monkeypatch):
    original_salt = settings.visitor_hash_salt
    original_version = settings.visitor_hash_salt_version
    try:
        monkeypatch.setattr(settings, "visitor_hash_salt", "", raising=False)
        monkeypatch.setattr(settings, "visitor_hash_salt_version", "1", raising=False)
        base = hash_visitor("1.2.3.4")
        assert base

        # 换盐：同一地址换出不同哈希
        monkeypatch.setattr(settings, "visitor_hash_salt", "another-salt", raising=False)
        rotated = hash_visitor("1.2.3.4")
        assert rotated != base

        # 同盐换版本号：也不同，避免「换了盐还能对上同一个人」
        monkeypatch.setattr(settings, "visitor_hash_salt_version", "2", raising=False)
        assert hash_visitor("1.2.3.4") != rotated

        # 空地址永远是 None，不生成假访客
        assert hash_visitor("") is None
    finally:
        settings.visitor_hash_salt = original_salt
        settings.visitor_hash_salt_version = original_version


def _load_generator():
    path = Path(__file__).resolve().parents[1] / "scripts" / "gen_metric_dictionary.py"
    spec = importlib.util.spec_from_file_location("gen_metric_dictionary", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_metric_dictionary_section_is_generated_from_definitions():
    module = _load_generator()
    section = module.render(
        [
            {
                "code": "mention_rate",
                "name": "提及率",
                "rule_version": 2,
                "formula": "提及数 | 有效数",
                "effective_from": "2026-11-01",
                "status": "active",
            }
        ]
    )
    # 表格里的竖线要转义，否则 markdown 表格会被公式拆坏
    assert "提及数 \\| 有效数" in section
    assert "v2" in section

    document = "# 标题\n\n正文\n"
    spliced = module.splice(document, section)
    assert module.BEGIN_MARK in spliced and module.END_MARK in spliced
    # 幂等：再拼一次内容不变
    assert module.splice(spliced, section) == spliced
    # 文档里已经存在这一段（说明脚本真的跑过）
    assert module.BEGIN_MARK in module.DOC_PATH.read_text(encoding="utf-8")

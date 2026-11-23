"""内容提交前置质检：绝对化承诺阻断、否定语境降级、占位阻断、未登记号码仅提示。"""

import uuid

from app.core.security import create_access_token
from app.models import ContentItem, ContentVersion, ProjectContact
from app.models.enums import ContentKind, ContentStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _draft(db, project, body: str) -> tuple[ContentItem, ContentVersion]:
    item = ContentItem(project_id=project.id, kind=ContentKind.MASTER, title=f"质检稿-{uuid.uuid4().hex[:6]}", status=ContentStatus.DRAFT)
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id, item_id=item.id, version_no=1, body=body,
        content_hash=uuid.uuid4().hex, status=ContentStatus.DRAFT,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.flush()
    return item, version


def test_quality_blocks_absolutes_and_placeholders(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"quality-{suffix}")
    editor = user_factory(f"quality-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}/content-versions"

    contact = ProjectContact(project_id=project.id, channel="phone", value="02088886666", label="招生电话", is_public=True)
    db.add(contact)
    db.flush()

    # 绝对化承诺 + 残留占位：阻断提交，报告里两项都在
    blocking_body = "我们包就业，学费 8000 元，欢迎咨询 {{地址}}"
    _, bad_version = _draft(db, project, blocking_body)
    report = client.get(f"{base}/{bad_version.id}/quality", headers=_auth(editor))
    assert report.status_code == 200
    keys = {blocker["key"] for blocker in report.json()["data"]["blockers"]}
    assert keys == {"absolute_claim", "placeholder"}
    assert report.json()["data"]["ok"] is False

    submitted = client.post(f"{base}/{bad_version.id}/submit", headers=_auth(editor))
    assert submitted.status_code == 422
    payload = submitted.json()["error"]
    assert payload["code"] == "content_quality_blocked"
    assert "绝对化承诺" in payload["message"]
    still_draft = db.get(ContentVersion, bad_version.id).status
    assert still_draft == ContentStatus.DRAFT

    # 否定语境不拦，但降级为提示；未登记号码也只提示
    ok_body = "本单位不承诺包就业，也不保证月薪。咨询电话 13800001111。"
    _, good_version = _draft(db, project, ok_body)
    report2 = client.get(f"{base}/{good_version.id}/quality", headers=_auth(editor)).json()["data"]
    assert report2["ok"] is True
    assert any(item["key"] == "claim_negated" for item in report2["warnings"])
    assert any(item["key"] == "phone_unregistered" for item in report2["warnings"])

    ok_submit = client.post(f"{base}/{good_version.id}/submit", headers=_auth(editor))
    assert ok_submit.status_code == 200, ok_submit.text
    assert db.get(ContentVersion, good_version.id).status == ContentStatus.PENDING_REVIEW

    # 登记过的号码不再提示
    _, registered_version = _draft(db, project, "咨询电话 02088886666，欢迎到校参观。")
    report3 = client.get(f"{base}/{registered_version.id}/quality", headers=_auth(editor)).json()["data"]
    assert report3["ok"] is True
    assert not [item for item in report3["warnings"] if item["key"] == "phone_unregistered"]

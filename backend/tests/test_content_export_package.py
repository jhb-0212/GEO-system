"""交付包导出：把已审正文整理成可直接粘进公司官网 CMS 的成品。"""

import uuid

from app.core.security import create_access_token
from app.models import PublicPage
from app.models.content import ContentItem
from app.models.enums import PagePublishStatus, PageType, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _make_version(client, base, user, title, body):
    item = client.post(f"{base}/contents", json={"title": title, "kind": "master"}, headers=_auth(user))
    assert item.status_code == 201, item.text
    item_id = item.json()["data"]["item_id"]
    version = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": body, "change_note": "交付包用例"},
        headers=_auth(user),
    )
    assert version.status_code == 201, version.text
    return item_id, version.json()["data"]["version_id"]


def test_export_package_has_markdown_html_and_checklist(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"export-{suffix}")
    editor = user_factory(f"exp-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}"

    body = "# 基地事实\n\n1500㎡ 线下场地。\n- 电话：19927547288\n- 地址：番禺\n\n<script>alert(1)</script>"
    # 标题用纯中文，验证"取不到英文单词时 slug 退回 content-<id>"
    _, version_id = _make_version(client, base, editor, "交付包联调甲", body)

    response = client.get(f"{base}/content-versions/{version_id}/export", headers=_auth(editor))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["markdown"].startswith("# 交付包联调甲")
    # markdown 里正文的 "# " 也要降级，交付包只能有一个一级标题
    assert "\n\n## 基地事实" in data["markdown"]
    assert "\n# 基地事实" not in data["markdown"]
    # 文章标题占 H1，正文里的 "# " 降一级成 H2
    assert "<h2>基地事实</h2>" in data["html"]
    assert "<li>电话：19927547288</li>" in data["html"]
    # 正文按纯文本处理：尖括号被转义，不会被当成标签塞进 CMS
    assert "&lt;script&gt;" in data["html"]
    assert "<script>" not in data["html"]
    assert len(data["checklist"]) == 5
    assert data["jsonld"][0]["@type"] == "Article"
    assert data["status"] in {"draft", "approved"}
    # 摘要不能把 markdown 标记或正文标签原样带出去
    assert data["meta_description"].startswith("基地事实 1500㎡")
    assert "#" not in data["meta_description"]
    # 纯中文标题取不到英文单词时，slug 退回 content-<item 前 8 位>，不能拼成日期/数字
    assert data["slug_suggestion"].startswith("content-")
    assert not data["slug_suggestion"].replace("content-", "").isdigit()


def test_export_package_uses_registered_page_as_canonical(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"export-canon-{suffix}")
    editor = user_factory(f"expc-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}"

    item_id, version_id = _make_version(client, base, editor, f"canon-{suffix}", "正文")
    row = db.get(ContentItem, uuid.UUID(item_id))
    assert row is not None
    db.add(
        PublicPage(
            project_id=project.id,
            slug=f"canon-{suffix}",
            title=f"canon-{suffix}",
            page_type=PageType.OTHER,
            url="http://www.gdccai.com/news/show-1.html",
            canonical_url="http://www.gdccai.com/news/show-1.html",
            publish_status=PagePublishStatus.PUBLISHED,
            content_item_id=row.id,
        )
    )
    db.commit()

    data = client.get(f"{base}/content-versions/{version_id}/export", headers=_auth(editor)).json()["data"]
    assert data["canonical_hint"] == "http://www.gdccai.com/news/show-1.html"
    assert data["jsonld"][0]["mainEntityOfPage"]["@id"] == data["canonical_hint"]

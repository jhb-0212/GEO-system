"""K8 微站：6 模块骨架、开关排序、公开渲染口径。

钉住四条：
1. 第一次 GET 自动建站并补齐 6 个模块，重复 GET 不会重复建；
2. 未发布时公开接口一律 404（与「不存在」同一句，不泄露存在性）；
3. 发布后公开接口只返回启用的模块，且按 sort_order 排序；
4. 模块内容体积超限被拒；slug 被别的项目占用返回 409。
"""

import uuid

from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import SiteModule, SiteSite
from app.models.enums import RoleCode

MODULE_TYPES = ["home", "services", "news", "download", "poster", "card"]


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _project_and_editor(project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"site-{suffix}")
    editor = user_factory(f"site-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    return project, editor


def test_first_get_provisions_six_modules(client, db, project_factory, user_factory, member_factory):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    resp = client.get(f"/api/v1/projects/{project.id}/site", headers=_auth(editor))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert [m["module_type"] for m in data["modules"]] == MODULE_TYPES
    # 只有首页默认启用：别的一开始是空内容，开着就是空段
    assert [m["is_active"] for m in data["modules"]] == [True, False, False, False, False, False]
    assert data["is_published"] is False
    assert data["slug"]

    again = client.get(f"/api/v1/projects/{project.id}/site", headers=_auth(editor))
    assert again.status_code == 200
    assert len(again.json()["data"]["modules"]) == 6
    assert db.scalar(select(func.count()).select_from(SiteSite).where(SiteSite.project_id == project.id)) == 1


def test_publish_and_public_render(client, db, project_factory, user_factory, member_factory):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    site = client.get(f"/api/v1/projects/{project.id}/site", headers=_auth(editor)).json()["data"]

    # 未发布：公开接口 404
    blocked = client.get(f"/api/v1/public/sites/{site['slug']}")
    assert blocked.status_code == 404, blocked.text
    assert blocked.json()["error"]["code"] == "site_not_found"

    # 启用「产品服务」并写内容，再发布
    updated = client.patch(
        f"/api/v1/projects/{project.id}/site/modules/services",
        json={"is_active": True, "content": {"items": [{"name": "AI 实训", "desc": "3 个月"}]}},
        headers=_auth(editor),
    )
    assert updated.status_code == 200, updated.text
    published = client.patch(
        f"/api/v1/projects/{project.id}/site", json={"is_published": True}, headers=_auth(editor)
    )
    assert published.status_code == 200, published.text

    public = client.get(f"/api/v1/public/sites/{site['slug']}")
    assert public.status_code == 200, public.text
    body = public.json()["data"]
    assert [m["module_type"] for m in body["modules"]] == ["home", "services"]
    assert body["modules"][1]["content"]["items"][0]["name"] == "AI 实训"


def test_public_sites_index_lists_published_only(
    client, db, project_factory, user_factory, member_factory
):
    """sitemap 数据源：只列已发布站点，未发布的不出现，含 slug 与标题。"""
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    site = client.get(f"/api/v1/projects/{project.id}/site", headers=_auth(editor)).json()["data"]

    index = client.get("/api/v1/public/sites")
    assert index.status_code == 200, index.text
    assert site["slug"] not in {row["slug"] for row in index.json()["data"]}

    client.patch(f"/api/v1/projects/{project.id}/site", json={"is_published": True}, headers=_auth(editor))
    index = client.get("/api/v1/public/sites")
    rows = {row["slug"]: row for row in index.json()["data"]}
    assert site["slug"] in rows
    assert rows[site["slug"]]["title"] == site["title"]
    # 索引不返回模块正文，避免被当成批量抓取接口
    assert "modules" not in rows[site["slug"]]


def test_module_sort_order_changes_public_order(client, db, project_factory, user_factory, member_factory):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    client.get(f"/api/v1/projects/{project.id}/site", headers=_auth(editor))
    client.patch(
        f"/api/v1/projects/{project.id}/site/modules/home",
        json={"sort_order": 5},
        headers=_auth(editor),
    )
    client.patch(
        f"/api/v1/projects/{project.id}/site/modules/news",
        json={"is_active": True, "sort_order": 0},
        headers=_auth(editor),
    )
    client.patch(
        f"/api/v1/projects/{project.id}/site", json={"is_published": True}, headers=_auth(editor)
    )
    site = db.scalar(select(SiteSite).where(SiteSite.project_id == project.id))
    public = client.get(f"/api/v1/public/sites/{site.slug}")
    assert [m["module_type"] for m in public.json()["data"]["modules"]] == ["news", "home"]


def test_content_size_limit(client, db, project_factory, user_factory, member_factory):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    client.get(f"/api/v1/projects/{project.id}/site", headers=_auth(editor))
    huge = {"paragraphs": ["x" * 2000 for _ in range(12)]}
    resp = client.patch(
        f"/api/v1/projects/{project.id}/site/modules/home",
        json={"content": huge},
        headers=_auth(editor),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "site_content_too_large"


def test_slug_conflict_between_projects(client, db, project_factory, user_factory, member_factory):
    project_a, editor_a = _project_and_editor(project_factory, user_factory, member_factory)
    project_b, editor_b = _project_and_editor(project_factory, user_factory, member_factory)
    client.get(f"/api/v1/projects/{project_a.id}/site", headers=_auth(editor_a))
    site_a = db.scalar(select(SiteSite).where(SiteSite.project_id == project_a.id))
    client.get(f"/api/v1/projects/{project_b.id}/site", headers=_auth(editor_b))

    resp = client.patch(
        f"/api/v1/projects/{project_b.id}/site", json={"slug": site_a.slug}, headers=_auth(editor_b)
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "site_slug_taken"


def test_unpublished_site_modules_not_rows_duplicated(client, db, project_factory, user_factory, member_factory):
    project, editor = _project_and_editor(project_factory, user_factory, member_factory)
    for _ in range(3):
        client.get(f"/api/v1/projects/{project.id}/site", headers=_auth(editor))
    assert (
        db.scalar(select(func.count()).select_from(SiteModule).where(SiteModule.project_id == project.id))
        == 6
    )

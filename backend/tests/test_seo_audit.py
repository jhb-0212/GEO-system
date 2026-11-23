"""SEO 核验：任意页面 HTML + 微站 head 字段（全部测试数据）。"""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode, SiteModuleType
from app.models.microsite import SiteModule, SiteSite
from app.services.seo_audit import audit_html


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


FULL_HTML = """
<html lang="zh-CN"><head>
<title>示例站</title>
<link rel="canonical" href="https://example.com/s/demo">
<meta name="description" content="简介">
<meta property="og:title" content="示例站">
<meta property="og:description" content="简介">
<meta property="og:image" content="https://example.com/a.jpg">
<meta property="og:url" content="https://example.com/s/demo">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{"@type":"Organization"}</script>
</head><body></body></html>
"""

PARTIAL_HTML = """<html><head><link rel="canonical" href="https://example.com/s/demo">
<meta name="description" content="简介"></head></html>"""


def test_audit_html_reports_missing_tags():
    assert audit_html(FULL_HTML)["ok"] is True

    partial = audit_html(PARTIAL_HTML)
    assert partial["ok"] is False
    assert set(partial["missing"]) == {"og:title", "og:description", "og:image", "og:url", "twitter:card", "json-ld"}

    custom = audit_html(PARTIAL_HTML, required=["canonical", "description"])
    assert custom["ok"] is True


def test_microsite_report_flags_missing_og_image(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"seo-{suffix}")
    admin = user_factory(f"seo-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    site = SiteSite(project_id=project.id, slug=f"seo-{suffix}", title="示例微站", intro="简介", is_published=True)
    db.add(site)
    db.flush()
    db.add(
        SiteModule(
            project_id=project.id, site_id=site.id, module_type=SiteModuleType.HOME,
            title="首页", content={"headline": "欢迎"}, sort_order=0,
        )
    )
    db.flush()

    report = client.get(
        f"/api/v1/projects/{project.id}/stats/seo-audit", headers=_auth(admin)
    ).json()["data"]
    site_item = report["sites"][0]
    assert "og:image" in site_item["missing"]
    assert "canonical" in site_item["present"]

    # 模块里放了图片后，og:image 立即算有；规则与前端一致
    db.add(
        SiteModule(
            project_id=project.id, site_id=site.id, module_type=SiteModuleType.POSTER,
            title="海报", content={"image": "https://cdn.example.com/poster.jpg"}, sort_order=1,
        )
    )
    db.flush()
    report2 = client.post(
        f"/api/v1/projects/{project.id}/stats/seo-audit/html",
        headers=_auth(admin),
        json={"html": FULL_HTML},
    ).json()["data"]
    assert report2["ok"] is True

    report3 = client.get(
        f"/api/v1/projects/{project.id}/stats/seo-audit", headers=_auth(admin)
    ).json()["data"]
    assert "og:image" not in report3["sites"][0]["missing"]


def test_microsite_report_without_site_is_honest(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"seo-empty-{suffix}")
    admin = user_factory(f"seo-empty-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    data = client.get(f"/api/v1/projects/{project.id}/stats/seo-audit", headers=_auth(admin)).json()["data"]
    assert data["ok"] is False
    assert data["sites"] == []
    assert "site_sites" in data["note"]

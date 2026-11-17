"""品牌口径配置接口的回归与权限边界。

覆盖：
- 未配置时 GET 返回 configured=false + 回退词表（让人能自查当前到底按什么判）；
- PUT 后 GET 立即反映新词表，且别名/标识/域名三类分开；
- 同一词条同时进 aliases 与 identifiers 会被拒绝（防止提及率被污染）；
- 只读角色不能写、跨项目不能读；
- 写入留审计，并按品牌口径作用面标注。
"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AuditLog, BrandProfile
from app.models.enums import RoleCode

BRAND_NAME = "广东省成才人工智能产业孵化有限公司"
ADDRESS = "番山创业中心1号楼2区2楼"


def _auth(user) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"
    }


def test_get_brand_profile_unconfigured_returns_fallback(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"bp-api-none-{suffix}", name="广州基地")
    editor = user_factory(f"bp-api-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.get(
        f"/api/v1/projects/{project.id}/brand-profile", headers=_auth(editor)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["configured"] is False
    assert data["effective_mention_terms"] == ["广州基地", project.code]
    assert data["effective_identifier_terms"] == []
    assert data["effective_owned_domains"] == []


def test_put_brand_profile_then_get_reflects_vocabulary(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"bp-api-put-{suffix}")
    editor = user_factory(f"bp-api-put-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    payload = {
        "canonical_name": BRAND_NAME,
        "aliases": ["成才", "广东省AI数字人才就业实训基地"],
        "identifiers": [ADDRESS, "13022038683"],
        "owned_domains": ["WWW.Chengcai-Edu.com"],
        "notes": "对外口径以工商全名为准",
    }
    resp = client.put(
        f"/api/v1/projects/{project.id}/brand-profile",
        json=payload,
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["configured"] is True
    assert data["canonical_name"] == BRAND_NAME
    # 域名归一：小写 + 去 www.
    assert data["owned_domains"] == ["chengcai-edu.com"]
    assert data["effective_mention_terms"] == [
        BRAND_NAME,
        "成才",
        "广东省AI数字人才就业实训基地",
    ]
    assert data["effective_identifier_terms"] == [ADDRESS, "13022038683"]
    assert data["effective_owned_domains"] == ["chengcai-edu.com"]

    # 二次 GET 与 PUT 返回一致（确认已落库，不是内存态）
    again = client.get(
        f"/api/v1/projects/{project.id}/brand-profile", headers=_auth(editor)
    )
    assert again.status_code == 200
    assert again.json()["data"]["effective_mention_terms"] == data["effective_mention_terms"]

    profile = db.scalar(select(BrandProfile).where(BrandProfile.project_id == project.id))
    assert profile is not None and profile.canonical_name == BRAND_NAME

    audit = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "brand.profile.upsert",
            AuditLog.project_id == project.id,
        )
    ).all()
    assert audit
    assert "brand_mentioned" in audit[-1].payload["affects"]


def test_put_rejects_term_in_both_aliases_and_identifiers(
    client, db, project_factory, user_factory, member_factory
):
    """把地址塞进别名会让「提及率」等于「提及或可识别率」，必须挡在入口。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"bp-api-overlap-{suffix}")
    editor = user_factory(f"bp-api-overlap-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.put(
        f"/api/v1/projects/{project.id}/brand-profile",
        json={
            "canonical_name": BRAND_NAME,
            "aliases": [ADDRESS],
            "identifiers": [ADDRESS],
        },
        headers=_auth(editor),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "brand_term_overlap"


def test_viewer_cannot_write_brand_profile(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"bp-api-viewer-{suffix}")
    viewer = user_factory(f"bp-api-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    read = client.get(
        f"/api/v1/projects/{project.id}/brand-profile", headers=_auth(viewer)
    )
    # monitoring.read 在只读角色集合里
    assert read.status_code == 200, read.text

    write = client.put(
        f"/api/v1/projects/{project.id}/brand-profile",
        json={"canonical_name": BRAND_NAME},
        headers=_auth(viewer),
    )
    assert write.status_code == 403, write.text


def test_brand_profile_cross_project_denied(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project_a = project_factory(f"bp-api-a-{suffix}")
    project_b = project_factory(f"bp-api-b-{suffix}")
    editor = user_factory(f"bp-api-x-{suffix}")
    member_factory(project_b, editor, RoleCode.EDITOR)

    resp = client.get(
        f"/api/v1/projects/{project_a.id}/brand-profile", headers=_auth(editor)
    )
    assert resp.status_code == 403, resp.text

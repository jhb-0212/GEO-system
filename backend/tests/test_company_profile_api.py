"""企业档案接口回归：完整度、字数规则、与 facts 的冲突闸门、权限边界。

覆盖：
- 未配置时 GET 返回 configured=false + 完整度 0 + 缺口清单；
- PUT 后 GET 立即反映，完整度按 16 项必填计算；
- 公司介绍少于 100 字被拒（对齐平台「≥100 字」规则）；
- 电话与 facts(contact) 不一致时拒绝写入，显式确认后才放行；
- 只读角色不能写；写入留审计并记录被确认的冲突。
"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AuditLog, BrandProfile, CompanyProfile, Fact
from app.models.enums import FactType, RoleCode

LONG_COPY = "广东省AI数字人才就业实训基地" * 10  # > 100 字，满足长文案下限


def _auth(user) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"
    }


def test_get_company_profile_unconfigured_lists_gaps(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cp-none-{suffix}")
    editor = user_factory(f"cp-none-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.get(
        f"/api/v1/projects/{project.id}/company-profile", headers=_auth(editor)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["configured"] is False
    assert data["completeness"] == 0
    assert "公司名称" in data["missing"]
    assert "公司介绍（≥100 字）" in data["missing"]


def test_put_company_profile_then_get_reflects_and_computes_completeness(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cp-put-{suffix}")
    editor = user_factory(f"cp-put-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    payload = {
        "legal_name": "广东省成才人工智能产业孵化有限公司",
        "brand_name": "广东省AI数字人才就业实训基地",
        "slogan": "授实用技术，铺成长坦途",
        "province": "广东广州",
        "business_phone": "020-88886666",
        "contact_email": "contact@example.com",
        "stores": ["广州市番禺区番山创业中心1号楼2区2楼", "广州市天河区体育西路1号"],
        "industries": ["职业技能培训", "人工智能"],
        "regions": ["广东", "广州"],
        "description": LONG_COPY,
        "founder_intro": LONG_COPY,
        "highlights": "线下20-30人小班面授，学员可拿商用作品集",
        "pain_points": "网上碎片化教程导致学完不会做项目",
        "story": "集团2019年起扎根珠三角开展职业教育",
        "products": [{"name": "AIGC漫剧培训", "summary": "100集实战"}],
    }
    resp = client.put(
        f"/api/v1/projects/{project.id}/company-profile",
        json=payload,
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["configured"] is True
    assert data["legal_name"] == payload["legal_name"]
    assert data["stores"] == payload["stores"]
    assert data["products"][0]["name"] == "AIGC漫剧培训"
    # 16 项必填填了 14 项；缺「售后热线」与「官网地址」（品牌设置未配域名，派生值为空）→ 88%。
    assert data["completeness"] == 88
    assert "售后热线" in data["missing"]
    assert "官网地址" in data["missing"]  # 派生值为空，缺口是真实存在的
    assert data["official_urls"] == []
    assert data["official_urls_source"] == "brand_profile"

    again = client.get(
        f"/api/v1/projects/{project.id}/company-profile", headers=_auth(editor)
    )
    assert again.json()["data"]["description"] == LONG_COPY


def test_official_urls_is_readonly_and_derived_from_brand(
    client, db, project_factory, user_factory, member_factory
):
    """官网域名只有一个写入口：品牌设置。档案里出现非空官网地址必须被拒绝。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cp-urls-{suffix}")
    editor = user_factory(f"cp-urls-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    base = f"/api/v1/projects/{project.id}/company-profile"

    db.add(
        BrandProfile(
            project_id=project.id,
            canonical_name="成才人工智能",
            owned_domains=["ccai.example.com", "www.ccai.example.com"],
            is_active=True,
        )
    )
    db.commit()

    rejected = client.put(
        base,
        json={"legal_name": "测试主体", "official_urls": ["https://other.example.com"]},
        headers=_auth(editor),
    )
    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["error"]["code"] == "official_urls_readonly"

    saved = client.put(base, json={"legal_name": "测试主体"}, headers=_auth(editor))
    assert saved.status_code == 200, saved.text
    data = saved.json()["data"]
    assert data["official_urls"] == ["ccai.example.com", "www.ccai.example.com"]
    assert data["official_urls_source"] == "brand_profile"
    # 品牌设置里有域名 → 「官网地址」这一项自动算已填，不需要在档案里再录一次
    assert "官网地址" not in data["missing"]


def test_short_description_rejected(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cp-short-{suffix}")
    editor = user_factory(f"cp-short-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.put(
        f"/api/v1/projects/{project.id}/company-profile",
        json={"legal_name": "测试主体", "description": "太短了"},
        headers=_auth(editor),
    )
    assert resp.status_code in (400, 422), resp.text


def test_phone_conflict_with_fact_requires_acknowledgement(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cp-conflict-{suffix}")
    editor = user_factory(f"cp-conflict-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    fact = Fact(
        project_id=project.id,
        fact_type=FactType.CONTACT,
        fact_key="业务电话",
        fact_value="020-88886666",
    )
    db.add(fact)
    db.commit()

    resp = client.put(
        f"/api/v1/projects/{project.id}/company-profile",
        json={"legal_name": "测试主体", "business_phone": "020-99999999"},
        headers=_auth(editor),
    )
    assert resp.status_code == 400, resp.text
    error = resp.json()["error"]
    assert error["code"] == "company_fact_conflict"
    assert "020-88886666" in error["message"]

    # 显式确认后放行，并把确认项写进审计。
    resp = client.put(
        f"/api/v1/projects/{project.id}/company-profile",
        json={
            "legal_name": "测试主体",
            "business_phone": "020-99999999",
            "acknowledged_conflicts": [f"business_phone:{fact.id}"],
        },
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["business_phone"] == "020-99999999"

    audit = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action == "company.profile.upsert",
        )
    ).all()
    assert len(audit) == 1
    assert f"business_phone:{fact.id}" in audit[0].payload["acknowledged_conflicts"]


def test_viewer_cannot_write_profile(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"cp-viewer-{suffix}")
    viewer = user_factory(f"cp-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    resp = client.put(
        f"/api/v1/projects/{project.id}/company-profile",
        json={"legal_name": "测试主体"},
        headers=_auth(viewer),
    )
    assert resp.status_code == 403, resp.text

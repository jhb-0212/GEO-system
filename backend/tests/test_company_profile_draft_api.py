"""企业档案「一键填表」回归：规则映射、AI 优先、模型失败回退、权限边界。

覆盖口径：
- 只用已批准事实：草稿状态的事实不许出现在建议字段里；
- 规则模式不创作文案（description/founder_intro 必须留空）；
- 有可用模型时 `mode=ai`，但事实已给的字段不许被模型覆盖；
- 模型不可用/返回不合法时退回规则模式，并在 note 里说明；
- 只读角色不能调用。
"""

import uuid
from app.services.company_draft import ChatTarget

from app.core.security import create_access_token
from app.models import BrandProfile, Fact, Question
from app.models.enums import FactStatus, FactType, QuestionStatus, QuestionType, RoleCode
from app.services import company_draft


def _auth(user) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"
    }


def _seed_project(db, project_factory, user_factory, member_factory, prefix: str):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"{prefix}-{suffix}")
    editor = user_factory(f"{prefix}-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    return project, editor


def test_draft_rule_mode_only_uses_approved_facts(
    client, db, project_factory, user_factory, member_factory
):
    project, editor = _seed_project(db, project_factory, user_factory, member_factory, "cp-draft")

    db.add_all(
        [
            Fact(
                project_id=project.id,
                fact_type=FactType.ORGANIZATION,
                fact_key="公司全称",
                fact_value="广东省成才人工智能产业孵化有限公司",
                approval_status=FactStatus.APPROVED,
            ),
            Fact(
                project_id=project.id,
                fact_type=FactType.CONTACT,
                fact_key="业务电话",
                fact_value="020-88886666",
                approval_status=FactStatus.APPROVED,
            ),
            Fact(
                project_id=project.id,
                fact_type=FactType.BASE_ADDRESS,
                fact_key="基地地址",
                fact_value="广州市天河区某路 1 号 3 层",
                approval_status=FactStatus.APPROVED,
            ),
            Fact(
                project_id=project.id,
                fact_type=FactType.COURSE_NAME,
                fact_key="课程名称",
                fact_value="AI 数据标注实战班",
                approval_status=FactStatus.APPROVED,
            ),
            # 草稿事实：没有被批准，不许进建议字段
            Fact(
                project_id=project.id,
                fact_type=FactType.CONTACT,
                fact_key="售后热线",
                fact_value="400-000-0000",
                approval_status=FactStatus.DRAFT,
            ),
        ]
    )
    db.add(
        Question(
            project_id=project.id,
            code=f"Q{uuid.uuid4().hex[:4]}",
            title="广州有哪些 AI 培训基地？",
            question_type=QuestionType.GENERAL,
            status=QuestionStatus.ACTIVE,
        )
    )
    db.commit()

    resp = client.post(
        f"/api/v1/projects/{project.id}/company-profile/draft?prefer=rule",
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["mode"] == "rule"
    assert data["model"] is None
    fields = data["fields"]
    assert fields["legal_name"] == "广东省成才人工智能产业孵化有限公司"
    assert fields["business_phone"] == "020-88886666"
    assert fields["stores"] == ["广州市天河区某路 1 号 3 层"]
    assert fields["products"][0]["name"] == "AI 数据标注实战班"
    # 草稿事实不进结果
    assert "service_hotline" not in fields
    # 规则模式不写长文案
    assert "description" not in fields
    # 证据计数如实反映：4 条已批准 + 1 道目标词
    assert data["evidence"]["facts"] == 4
    assert data["evidence"]["questions"] == 1
    assert data["basis"]["legal_name"].startswith("事实库")

    # 不落库：调用前后档案仍为空
    profile = client.get(
        f"/api/v1/projects/{project.id}/company-profile", headers=_auth(editor)
    ).json()["data"]
    assert profile["configured"] is False


def test_draft_prefers_model_but_keeps_fact_fields(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project, editor = _seed_project(db, project_factory, user_factory, member_factory, "cp-ai")
    db.add(
        Fact(
            project_id=project.id,
            fact_type=FactType.ORGANIZATION,
            fact_key="公司全称",
            fact_value="广东省成才人工智能产业孵化有限公司",
            approval_status=FactStatus.APPROVED,
        )
    )
    db.commit()

    long_copy = "本基地面向零基础转行者提供 AI 训练与项目制实训，课程按岗位拆解，实训结束可独立完成标注与评测任务。" * 2
    monkeypatch.setattr(
        company_draft,
        "pick_chat_target",
        lambda db: ChatTarget("https://api.deepseek.com", "deepseek-chat", "sk-test"),
    )
    monkeypatch.setattr(
        company_draft,
        "draft_with_model",
        lambda target, evidence: {
            "legal_name": "模型瞎写的名字",
            "slogan": "授实用技术，铺成长坦途",
            "description": long_copy,
            "products": [{"name": "AI 数据标注实战班", "summary": "12 周项目制", "highlights": None}],
        },
    )

    resp = client.post(
        f"/api/v1/projects/{project.id}/company-profile/draft", headers=_auth(editor)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["mode"] == "ai"
    assert data["model"] == "deepseek-chat"
    fields = data["fields"]
    # 事实优先：模型不能改公司名称
    assert fields["legal_name"] == "广东省成才人工智能产业孵化有限公司"
    assert fields["slogan"] == "授实用技术，铺成长坦途"
    assert len(fields["description"]) >= 100
    assert fields["products"][0]["summary"] == "12 周项目制"
    assert data["basis"]["slogan"].startswith("模型起草")


def test_draft_falls_back_to_rule_when_model_fails(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project, editor = _seed_project(db, project_factory, user_factory, member_factory, "cp-fail")
    db.add(
        Fact(
            project_id=project.id,
            fact_type=FactType.CONTACT,
            fact_key="业务电话",
            fact_value="020-88886666",
            approval_status=FactStatus.APPROVED,
        )
    )
    db.commit()

    monkeypatch.setattr(
        company_draft,
        "pick_chat_target",
        lambda db: ChatTarget("https://api.deepseek.com", "deepseek-chat", "sk-test"),
    )
    monkeypatch.setattr(company_draft, "draft_with_model", lambda target, evidence: None)

    resp = client.post(
        f"/api/v1/projects/{project.id}/company-profile/draft", headers=_auth(editor)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["mode"] == "rule"
    assert data["fields"]["business_phone"] == "020-88886666"
    assert "退回事实整理" in (data["note"] or "")


def test_draft_ignores_short_or_fake_model_copy(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project, editor = _seed_project(db, project_factory, user_factory, member_factory, "cp-clip")
    monkeypatch.setattr(
        company_draft,
        "pick_chat_target",
        lambda db: ChatTarget("https://api.deepseek.com", "deepseek-chat", "sk-test"),
    )
    monkeypatch.setattr(
        company_draft,
        "draft_with_model",
        lambda target, evidence: {
            "description": "太短，不足以判断业务主体",  # <100 字，必须丢弃
            "products": [{"name": "   "}, {"name": "AI 数据标注实战班"}],
            "highlights": "x" * 800,  # 超 500 字，必须截断
            # 模型把 stores 写成了对象数组，这里要能取到网点名，且不能连累其他字段
            "stores": [{"name": "番山创业中心1号楼2区207", "address": "广州番禺"}],
        },
    )

    resp = client.post(
        f"/api/v1/projects/{project.id}/company-profile/draft", headers=_auth(editor)
    )
    assert resp.status_code == 200, resp.text
    fields = resp.json()["data"]["fields"]
    assert "description" not in fields
    assert [item["name"] for item in fields["products"]] == ["AI 数据标注实战班"]
    assert len(fields["highlights"]) == 500
    assert fields["stores"] == ["番山创业中心1号楼2区207"]


def test_draft_requires_write_permission(
    client, db, project_factory, user_factory, member_factory
):
    project, _editor = _seed_project(db, project_factory, user_factory, member_factory, "cp-view")
    suffix = uuid.uuid4().hex[:6]
    viewer = user_factory(f"cp-view-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    resp = client.post(
        f"/api/v1/projects/{project.id}/company-profile/draft", headers=_auth(viewer)
    )
    assert resp.status_code == 403, resp.text



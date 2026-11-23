"""行业预设与项目策略：通用默认来自 JSON，项目可覆盖；不碰存量行为。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models.enums import ContentKind, ContentStatus, RoleCode
from app.models.industry import Organization, ProjectStrategy
from app.services.content_quality import run_quality_check
from app.services.industry_presets import preset_config, project_industry_config, upsert_strategy
from app.models import ContentItem, ContentVersion


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_defaults_are_neutral_not_education():
    """默认必须是中性：模块级默认词表里不能出现教育培训专属词。"""
    from app.services.content_quality import ABSOLUTE_CLAIMS

    assert "包就业" not in ABSOLUTE_CLAIMS
    assert "最权威" in ABSOLUTE_CLAIMS
    assert preset_config()["code"] == "neutral"


def test_unselected_project_is_explicit_not_silent(client, db, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    # 故意建一个没有行业策略的项目
    from app.models import Project
    from app.models.enums import ProjectStatus
    from app.models.industry import Organization

    org = db.scalar(select(Organization).where(Organization.code == "default-client"))
    if org is None:
        org = Organization(code="default-client", name="默认客户", status="active", branding={})
        db.add(org)
        db.flush()
    project = Project(
        code=f"no-preset-{suffix}", name="未选行业", status=ProjectStatus.ACTIVE,
        timezone="Asia/Shanghai", organization_id=org.id,
    )
    db.add(project)
    db.flush()
    user = user_factory(f"no-preset-{suffix}")
    member_factory(project, user, RoleCode.VIEWER)

    status = client.get(
        f"/api/v1/projects/{project.id}/stats/industry", headers=_auth(user)
    ).json()["data"]
    assert status["selected"] is False
    assert status["preset_code"] == "neutral"
    assert "未选择行业预设" in status["message"]

    config = project_industry_config(db, project.id)
    assert config["code"] == "neutral"
    # 中性预设不含行业词（如「就业率」），只保留与行业无关的通用数字表达
    terms = config["quality"]["result_number_terms"]
    assert "就业率" not in terms
    assert "%" in terms

    # 默认识别题目：中性预设没有基线题目，必须明确报错，而不是借用教育那 6 题
    from app.services.question_baseline import activate_technical_baseline

    try:
        activate_technical_baseline(db, project.code, dry_run=True)
    except ValueError as exc:
        assert "未定义基线题目" in str(exc)
    else:
        raise AssertionError("中性预设不应静默套用其他行业的基线题目")


def test_project_strategy_overrides_quality_terms(db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"industry-{suffix}")
    editor = user_factory(f"industry-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    upsert_strategy(
        db, project.id,
        overrides={"quality": {"absolute_claims": ["绝对第一"]}},
        note="客户自定高风险词",
    )
    db.flush()

    config = project_industry_config(db, project.id)
    assert config["quality"]["absolute_claims"] == ["绝对第一"]

    # 该项目的策略生效：预设词不再命中，自定义词命中
    report = run_quality_check(
        "我们绝对第一，欢迎参观。", set(), claims=config["quality"]["absolute_claims"],
    )
    assert report["ok"] is False
    assert {item["key"] for item in report["blockers"]} == {"absolute_claim"}

    legacy = run_quality_check("我们包就业。", set(), claims=config["quality"]["absolute_claims"])
    assert legacy["ok"] is True


def test_fact_type_labels_come_from_strategy(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"labels-{suffix}")
    viewer = user_factory(f"labels-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    types = client.get(
        f"/api/v1/projects/{project.id}/facts/types", headers=_auth(viewer)
    ).json()["data"]
    labels = {item["value"]: item["label"] for item in types}
    assert labels["course_name"] == "课程名称"

    upsert_strategy(db, project.id, overrides={"labels": {"fact_types": {"course_name": "产品名称"}}})
    db.flush()
    types2 = client.get(
        f"/api/v1/projects/{project.id}/facts/types", headers=_auth(viewer)
    ).json()["data"]
    assert {item["value"]: item["label"] for item in types2}["course_name"] == "产品名称"


def test_project_creation_attaches_default_organization_and_strategy(client, db, user_factory):
    suffix = uuid.uuid4().hex[:6]
    admin = user_factory(f"org-admin-{suffix}", is_system_admin=True)
    created = client.post(
        "/api/v1/projects",
        headers=_auth(admin),
        json={"code": f"org-{suffix}", "name": "客户二项目"},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["data"]["id"]

    from app.models import Project

    project = db.get(Project, uuid.UUID(project_id))
    org = db.scalar(select(Organization).where(Organization.id == project.organization_id))
    assert org is not None and org.code == "default-client"
    # 新建项目不预选行业：策略为空，接口明确 selected=false
    strategy = db.scalar(
        select(ProjectStrategy).where(ProjectStrategy.project_id == project.id, ProjectStrategy.strategy_key == "industry")
    )
    assert strategy is None
    status = client.get(
        f"/api/v1/projects/{project.id}/stats/industry", headers=_auth(admin)
    ).json()["data"]
    assert status["selected"] is False
    assert status["preset_code"] == "neutral"

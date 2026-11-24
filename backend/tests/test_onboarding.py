"""开通向导：填表 → 派生草稿 → 确认落库；幂等、不猜行业。"""

import uuid

from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import BrandProfile, Channel, Competitor, MonitoringRound, Question
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _payload(preset: str = "edu-training", engines: list[str] | None = None) -> dict:
    return {
        "brand": {
            "name": "广州示例基地",
            "aliases": ["示例基地", "示例"],
            "domains": ["example.com"],
            "region": "广州",
        },
        "industry_preset": preset,
        "products": ["AI 实训", "短视频实训", "办公自动化实训"],
        "competitors": [
            {"name": "竞品甲", "domain": "a.example"},
            {"name": "竞品乙", "domain": "b.example"},
            {"name": "竞品丙", "domain": "c.example"},
        ],
        "engines": engines or [],
        "samples_per_cell": 1,
    }


def test_preview_derives_but_writes_nothing(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"onb-{suffix}")
    admin = user_factory(f"onb-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    before = db.scalar(select(func.count(BrandProfile.id)))
    preview = client.post(
        f"/api/v1/projects/{project.id}/onboarding/preview", headers=_auth(admin), json=_payload()
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert 8 <= len(data["derived"]["questions"]) <= 12
    assert data["derived"]["questions"][0]["code"] == "Q01"
    assert len(data["derived"]["channels"]) == 10
    assert data["derived"]["plan"]["cells"] == len(data["derived"]["questions"])
    assert db.scalar(select(func.count(BrandProfile.id))) == before


def test_apply_creates_drafts_and_is_idempotent(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"onb-apply-{suffix}")
    admin = user_factory(f"onb-apply-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    apply = client.post(
        f"/api/v1/projects/{project.id}/onboarding/apply", headers=_auth(admin), json=_payload()
    )
    assert apply.status_code == 200, apply.text
    result = apply.json()["data"]
    assert result["brand"]["created"] == 1
    assert result["competitors"]["created"] == 3
    assert 8 <= result["questions"]["created"] <= 12
    assert result["channels"]["created"] == 10
    assert result["round_id"] is not None
    assert result["tasks_created"] == 0  # 没有引擎入口时不建任务

    assert db.scalar(select(func.count(Question.id)).where(Question.project_id == project.id)) == result["questions"]["created"]
    assert db.scalar(select(func.count(Channel.id)).where(Channel.project_id == project.id)) == 10
    assert db.scalar(
        select(func.count(Competitor.id)).where(Competitor.project_id == project.id)
    ) == 3
    assert db.scalar(
        select(func.count(MonitoringRound.id)).where(MonitoringRound.project_id == project.id)
    ) == 1

    second = client.post(
        f"/api/v1/projects/{project.id}/onboarding/apply", headers=_auth(admin), json=_payload()
    ).json()["data"]
    assert second["questions"]["created"] == 0
    assert second["channels"]["created"] == 0
    assert second["competitors"]["created"] == 0
    assert second["round_id"] == result["round_id"]


def test_neutral_preset_works_without_industry_words(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"onb-neutral-{suffix}")
    admin = user_factory(f"onb-neutral-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    preview = client.post(
        f"/api/v1/projects/{project.id}/onboarding/preview",
        headers=_auth(admin),
        json=_payload(preset="neutral"),
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert data["preset"]["code"] == "neutral"
    assert len(data["derived"]["channels"]) == 8


def test_missing_preset_is_rejected(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"onb-nopreset-{suffix}")
    admin = user_factory(f"onb-nopreset-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    payload = _payload()
    payload["industry_preset"] = ""
    resp = client.post(
        f"/api/v1/projects/{project.id}/onboarding/preview", headers=_auth(admin), json=payload
    )
    assert resp.status_code in (400, 422), resp.text
    assert resp.json()["error"]["code"] == "onboarding_preset_required"


def test_presets_are_listed_without_default_hint(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"onb-presets-{suffix}")
    user = user_factory(f"onb-presets-user-{suffix}")
    member_factory(project, user, RoleCode.PROJECT_ADMIN)
    data = client.get(
        f"/api/v1/projects/{project.id}/industry-presets", headers=_auth(user)
    ).json()["data"]
    codes = {item["code"] for item in data}
    assert {"neutral", "edu-training"} <= codes

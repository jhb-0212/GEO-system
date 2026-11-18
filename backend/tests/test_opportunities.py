"""机会中心最小闭环：创建、评分、列表、状态更新与审计。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AuditLog, Opportunity
from app.models.enums import OpportunityGapType, OpportunityStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _factors(**overrides) -> dict:
    base = {
        "business_value": 5,
        "competitor_gap": 5,
        "material_readiness": 4,
        "implementation_cost": 2,
        "channel_authorization": 4,
        "verifiability": 5,
    }
    base.update(overrides)
    return base


def test_create_opportunity_scores_and_lists(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"op-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.post(
        f"/api/v1/projects/{project.id}/opportunities",
        json={
            "title": "补一篇课程对比页",
            "gap_type": OpportunityGapType.OWN_PAGE.value,
            "evidence_refs": [{"type": "citation", "id": "c-1"}],
            "score_factors": _factors(),
            "owner_id": str(editor.id),
        },
        headers=_auth(editor),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["title"] == "补一篇课程对比页"
    assert data["gap_type"] == OpportunityGapType.OWN_PAGE.value
    assert data["status"] == OpportunityStatus.OPEN.value
    assert data["priority_score"] == 4.5
    assert data["score_weights"]["business_value"] == 1.0
    assert data["owner_name"] == editor.display_name

    listed = client.get(
        f"/api/v1/projects/{project.id}/opportunities?status=open",
        headers=_auth(editor),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] == 1
    assert listed.json()["data"][0]["id"] == data["id"]

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "opportunity.create",
            AuditLog.target_id == uuid.UUID(data["id"]),
        )
    )
    assert audit is not None
    assert audit.payload["priority_score"] == 4.5


def test_update_opportunity_status_and_rescore(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"op-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)

    created = client.post(
        f"/api/v1/projects/{project.id}/opportunities",
        json={
            "title": "补媒体报道",
            "gap_type": OpportunityGapType.MEDIA_REPORT.value,
            "score_factors": _factors(),
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    opportunity_id = created.json()["data"]["id"]

    updated = client.patch(
        f"/api/v1/projects/{project.id}/opportunities/{opportunity_id}",
        json={
            "status": OpportunityStatus.IN_PROGRESS.value,
            "score_factors": _factors(business_value=1, implementation_cost=5),
        },
        headers=_auth(editor),
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["status"] == OpportunityStatus.IN_PROGRESS.value
    assert data["score_factors"]["business_value"] == 1
    assert data["priority_score"] == 3.33

    db.refresh(db.get(Opportunity, uuid.UUID(opportunity_id)))
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "opportunity.update",
            AuditLog.target_id == uuid.UUID(opportunity_id),
        )
    )
    assert audit is not None
    assert "status" in audit.payload["changed"]


def test_opportunity_rejects_out_of_range_factor(
    client, project_factory, user_factory, member_factory
):
    project = project_factory(f"op-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.post(
        f"/api/v1/projects/{project.id}/opportunities",
        json={
            "title": "非法评分",
            "gap_type": OpportunityGapType.UGC.value,
            "score_factors": _factors(business_value=6),
        },
        headers=_auth(editor),
    )
    assert resp.status_code == 422
